"""
PostgreSQL + PGVector storage backend for efficient vector similarity search.
Uses pgvector extension for fast cosine similarity operations.
"""

import logging
from typing import Optional, List, Tuple, Dict
from datetime import datetime, timezone
import numpy as np

logger = logging.getLogger(__name__)


def _to_utc_iso(dt) -> Optional[str]:
    """Convert a datetime to UTC ISO 8601 string ending with Z."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat() + 'Z'

# Lazy imports - only load when actually used to avoid dependency errors
asyncpg = None
register_vector = None

def _ensure_imports():
    """Lazy import of asyncpg and pgvector"""
    global asyncpg, register_vector
    if asyncpg is None:
        try:
            import asyncpg as _asyncpg
            from pgvector.asyncpg import register_vector as _register_vector
            asyncpg = _asyncpg
            register_vector = _register_vector
        except ImportError as e:
            raise ImportError(
                "PGVector dependencies not installed. "
                "Run: pip install asyncpg==0.29.0 pgvector==0.2.4 psycopg2-binary==2.9.9"
            ) from e


class PGVectorStorageService:
    """
    Storage service using PostgreSQL with pgvector extension.
    Provides efficient vector similarity search for query caching.
    """

    def __init__(
        self,
        connection_string: str,
        table_name: str = "cached_queries",
        query_log_table_name: str = "query_logs",
        databricks_pat: str = None,
        databricks_host: str = None,
        lakebase_instance_name: str = None,
        cache_ttl_hours: float = 24
    ):
        self.connection_string = connection_string
        self.table_name = self._normalize_table_name(table_name)
        self.query_log_table_name = self._normalize_table_name(query_log_table_name)
        self.databricks_pat = databricks_pat
        # Ensure host has https:// prefix
        self.databricks_host = databricks_host
        if self.databricks_host and not self.databricks_host.startswith("http"):
            self.databricks_host = f"https://{self.databricks_host}"
        self.lakebase_instance_name = lakebase_instance_name
        self.cache_ttl_hours = cache_ttl_hours
        self.pool = None
        self.oauth_token = None

    def _normalize_table_name(self, table_name: str) -> str:
        """Convert Databricks catalog.schema.table to PostgreSQL schema.table format."""
        table_parts = table_name.split('.')
        if len(table_parts) == 3:
            return f"{table_parts[1]}.{table_parts[2]}"
        elif len(table_parts) == 2:
            return table_name
        else:
            return f"public.{table_name}"

    async def initialize(self):
        """Initialize connection pool and ensure table exists"""
        _ensure_imports()

        if self.databricks_pat and self.databricks_host and self.lakebase_instance_name:
            logger.info("Lakebase mode: getting instance details for %s", self.lakebase_instance_name)

            try:
                import uuid
                from urllib.parse import quote_plus

                instance_name = self.lakebase_instance_name
                is_hostname = ".database." in instance_name
                # Normalize project name: "projects/foo" → "foo"
                is_autoscaling = instance_name.startswith("projects/") or (not is_hostname and "/" not in instance_name)
                project_id = instance_name.replace("projects/", "") if instance_name.startswith("projects/") else instance_name

                if is_hostname:
                    # Direct hostname provided — generate credentials via Provisioned API
                    logger.info("Using direct hostname: %s", instance_name)
                    hostname = instance_name
                    connection_string = await self._build_connection_string_with_creds(
                        hostname, quote_plus, uuid
                    )
                elif is_autoscaling:
                    # Lakebase Autoscaling: use SDK postgres.generate_database_credential
                    logger.info("Lakebase Autoscaling project: %s", project_id)
                    hostname, endpoint_name = await self._resolve_autoscaling_endpoint(project_id)
                    logger.info("Autoscaling endpoint: %s (%s)", hostname, endpoint_name)
                    connection_string = self._build_autoscaling_connection_string(
                        hostname, endpoint_name, quote_plus
                    )
                else:
                    # Lakebase Provisioned: resolve hostname via Database API
                    logger.info("Lakebase Provisioned instance: %s", instance_name)
                    hostname = await self._resolve_provisioned_hostname(instance_name)
                    logger.info("Provisioned instance hostname: %s", hostname)
                    connection_string = await self._build_connection_string_with_creds(
                        hostname, quote_plus, uuid
                    )

            except Exception as e:
                logger.exception("Failed to get Lakebase details")
                raise ValueError(f"Cannot initialize Lakebase connection: {e}. Please check your instance name and credentials.")
        else:
            connection_string = self.connection_string

        # SSL configuration
        connection_string = connection_string.replace('?sslmode=require', '').replace('&sslmode=require', '')

        import ssl as ssl_module
        ssl_context = ssl_module.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl_module.CERT_NONE

        self.pool = await asyncpg.create_pool(
            connection_string,
            min_size=2,
            max_size=10,
            command_timeout=60,
            ssl=ssl_context
        )

        logger.info("Connection pool created with SSL")

        async with self.pool.acquire() as conn:
            await self._ensure_extension(conn)
            await register_vector(conn)
            await self._ensure_table(conn)
            await self._ensure_query_log_table(conn)

    async def _build_connection_string_with_creds(self, hostname, quote_plus, uuid):
        """Generate OAuth credentials and build connection string for a Lakebase hostname."""
        import httpx

        oauth_token = None
        username = None

        async with httpx.AsyncClient() as http_client:
            # Try to generate a database-specific credential
            try:
                cred_url = f"{self.databricks_host}/api/2.0/database/credentials/generate"
                response = await http_client.post(
                    cred_url,
                    headers={"Authorization": f"Bearer {self.databricks_pat}"},
                    json={"request_id": str(uuid.uuid4())}
                )
                response.raise_for_status()
                cred_data = response.json()
                oauth_token = cred_data.get("token")
                logger.info("Database credential generated (expires in %ds)", cred_data.get("expires_in", 3600))
            except Exception as e:
                # Credential generation failed (e.g. token lacks database scope).
                # Use the provided token directly — works with Autoscaling Lakebase.
                logger.info("Credential generation failed (%s), using token directly as password", e)
                oauth_token = self.databricks_pat

            # Get current username
            try:
                user_url = f"{self.databricks_host}/api/2.0/preview/scim/v2/Me"
                response = await http_client.get(
                    user_url,
                    headers={"Authorization": f"Bearer {self.databricks_pat}"}
                )
                response.raise_for_status()
                username = response.json().get("userName")
            except Exception as e:
                logger.warning("Failed to get username via SCIM (%s), using connection_string user", e)
                # Extract user from the existing connection string if available
                if self.connection_string and "@" in self.connection_string:
                    from urllib.parse import urlparse, unquote
                    parsed = urlparse(self.connection_string)
                    username = unquote(parsed.username) if parsed.username else None

        if not username:
            raise ValueError("Cannot determine username for Lakebase connection")

        return f"postgresql://{quote_plus(username)}:{quote_plus(oauth_token)}@{hostname}:5432/databricks_postgres"

    def _get_lakebase_sdk_client(self):
        """Create a Databricks SDK WorkspaceClient for Lakebase operations.

        Supports lakebase_service_token formats:
          - PAT:   "dapi..."                    → WorkspaceClient(token=..., auth_type="pat")
          - SP:    "client_id:client_secret"    → WorkspaceClient(client_id=..., client_secret=...)
          - OAuth: "eyJ..."                     → WorkspaceClient(token=..., auth_type="pat")
        """
        from databricks.sdk import WorkspaceClient

        token = self.databricks_pat or ""

        if ":" in token and not token.startswith("dapi") and not token.startswith("eyJ"):
            client_id, client_secret = token.split(":", 1)
            logger.info("Lakebase auth: SP OAuth (client_id=%s...)", client_id[:12])
            return WorkspaceClient(
                host=self.databricks_host,
                client_id=client_id,
                client_secret=client_secret,
            )
        elif token:
            logger.info("Lakebase auth: %s", "PAT" if token.startswith("dapi") else "token")
            return WorkspaceClient(
                host=self.databricks_host,
                token=token,
                auth_type="pat"
            )
        else:
            from app.auth import get_service_principal_client
            client = get_service_principal_client()
            if not client:
                raise ValueError("No Lakebase service token configured")
            return client

    async def _resolve_autoscaling_endpoint(self, project_id: str) -> tuple:
        """Resolve Lakebase Autoscaling project to (hostname, endpoint_name) using SDK."""
        client = self._get_lakebase_sdk_client()
        endpoints = client.api_client.do(
            'GET',
            f'/api/2.0/postgres/projects/{project_id}/branches/production/endpoints'
        )
        eps = endpoints.get("endpoints", [])
        if not eps:
            raise ValueError(f"No endpoints found for Autoscaling project '{project_id}'")
        ep = eps[0]
        hostname = ep["status"]["hosts"]["host"]
        endpoint_name = ep["name"]
        return hostname, endpoint_name

    def _build_autoscaling_connection_string(self, hostname: str, endpoint_name: str, quote_plus) -> str:
        """Generate JWT credential for Autoscaling Lakebase and build connection string."""
        client = self._get_lakebase_sdk_client()
        cred = client.postgres.generate_database_credential(endpoint=endpoint_name)
        username = client.current_user.me().user_name
        logger.info("Autoscaling JWT credential generated for %s", username)

        return f"postgresql://{quote_plus(username)}:{quote_plus(cred.token)}@{hostname}:5432/databricks_postgres"

    async def _resolve_provisioned_hostname(self, instance_name: str) -> str:
        """Resolve Lakebase Provisioned instance to its hostname."""
        import httpx

        async with httpx.AsyncClient() as http_client:
            url = f"{self.databricks_host}/api/2.0/database/instances/{instance_name}"
            response = await http_client.get(
                url,
                headers={"Authorization": f"Bearer {self.databricks_pat}"}
            )
            response.raise_for_status()
            data = response.json()
            return data.get("read_write_dns") or data.get("host")

    async def _ensure_extension(self, conn):
        """Ensure pgvector extension is installed"""
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

    async def _ensure_table(self, conn):
        """Create the cached_queries table if it doesn't exist"""
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id SERIAL PRIMARY KEY,
                query_text TEXT NOT NULL,
                query_embedding vector(1024),
                sql_query TEXT NOT NULL,
                identity VARCHAR(255) NOT NULL,
                genie_space_id VARCHAR(255) NOT NULL,
                created_at TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                last_used TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                use_count INTEGER DEFAULT 1
            )
        """)

        idx_base = self.table_name.replace('.', '_')

        await conn.execute(f"""
            CREATE INDEX IF NOT EXISTS {idx_base}_embedding_idx
            ON {self.table_name}
            USING ivfflat (query_embedding vector_cosine_ops)
            WITH (lists = 100)
        """)

        await conn.execute(f"""
            CREATE INDEX IF NOT EXISTS {idx_base}_identity_idx
            ON {self.table_name} (identity)
        """)

        await conn.execute(f"""
            CREATE INDEX IF NOT EXISTS {idx_base}_space_idx
            ON {self.table_name} (genie_space_id)
        """)

        logger.info("PGVector table '%s' initialized", self.table_name)

    async def _ensure_query_log_table(self, conn):
        """Create the query_logs table if it doesn't exist"""
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.query_log_table_name} (
                id SERIAL PRIMARY KEY,
                query_id VARCHAR(255) NOT NULL UNIQUE,
                query_text TEXT NOT NULL,
                identity VARCHAR(255) NOT NULL,
                stage VARCHAR(50) NOT NULL,
                genie_space_id VARCHAR(255),
                from_cache BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                updated_at TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
            )
        """)

        log_idx_base = self.query_log_table_name.replace('.', '_')

        await conn.execute(f"""
            CREATE INDEX IF NOT EXISTS {log_idx_base}_identity_idx
            ON {self.query_log_table_name} (identity)
        """)

        await conn.execute(f"""
            CREATE INDEX IF NOT EXISTS {log_idx_base}_created_idx
            ON {self.query_log_table_name} (created_at DESC)
        """)

        logger.info("Query log table '%s' initialized", self.query_log_table_name)

    async def search_similar_query(
        self,
        query_embedding: List[float],
        identity: str,
        threshold: float = 0.92,
        genie_space_id: Optional[str] = None,
        cache_ttl_hours: float = None,
        shared_cache: bool = True
    ) -> Optional[Tuple[int, str, str, float]]:
        """
        Search for similar cached queries using vector similarity.
        Only matches entries within the freshness window (cache_ttl_hours).
        Entries are never deleted - they stay in history forever.
        If shared_cache=True, searches all entries regardless of identity.
        If shared_cache=False, filters by identity.
        """
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        ttl = cache_ttl_hours if cache_ttl_hours is not None else self.cache_ttl_hours

        embedding_array = np.array(query_embedding, dtype=np.float32)

        async with self.pool.acquire() as conn:
            await register_vector(conn)

            # Build query with optional filters
            filters = []
            params = [embedding_array]
            param_idx = 2

            if not shared_cache:
                filters.append(f"identity = ${param_idx}")
                params.append(identity)
                param_idx += 1

            # Threshold parameter
            params.append(threshold)
            threshold_param_idx = param_idx
            param_idx += 1

            # genie_space_id is stored for audit but not used as a search filter,
            # since the same query text produces the same SQL regardless of space


            # Freshness window: only match entries within TTL (0 = no limit)
            if ttl and ttl > 0:
                ttl_seconds = int(ttl * 3600)
                filters.append(f"created_at > (CURRENT_TIMESTAMP - INTERVAL '{ttl_seconds} seconds')")

            # Cosine similarity: <=> returns cosine distance, similarity = 1 - distance
            filters.append(f"(1 - (query_embedding <=> $1::vector)) >= ${threshold_param_idx}")

            where_clause = " AND ".join(filters)

            query = f"""
                SELECT
                    id,
                    query_text,
                    sql_query,
                    1 - (query_embedding <=> $1::vector) AS similarity
                FROM {self.table_name}
                WHERE {where_clause}
                ORDER BY query_embedding <=> $1::vector
                LIMIT 1
            """

            logger.info("Cache search: table=%s threshold=%.2f ttl=%s shared=%s space=%s filters=%d SQL: %s params_count=%d",
                        self.table_name, threshold, ttl or "unlimited", shared_cache,
                        genie_space_id or "any", len(filters), where_clause[:200], len(params))

            row = await conn.fetchrow(query, *params)

            if row:
                await self._update_usage(conn, row['id'])
                logger.info("Cache HIT id=%s similarity=%.3f query=%s", row['id'], row['similarity'], row['query_text'][:50])
                return (row['id'], row['query_text'], row['sql_query'], float(row['similarity']))

            # Debug: check what's in the table
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {self.table_name}")
            if count > 0:
                best = await conn.fetchrow(f"""
                    SELECT id, query_text, 1 - (query_embedding <=> $1::vector) AS sim
                    FROM {self.table_name} ORDER BY query_embedding <=> $1::vector LIMIT 1
                """, embedding_array)
                if best:
                    logger.info("Cache MISS: %d entries, best_sim=%.3f best_query=%s (threshold=%.2f ttl=%s)",
                                count, best['sim'], best['query_text'][:50], threshold, ttl or "unlimited")
                else:
                    logger.info("Cache MISS: %d entries but no vector match found", count)
            else:
                logger.info("Cache MISS: table is empty")
            return None

    async def _update_usage(self, conn, cache_id: int):
        """Update last_used and use_count for a cache entry"""
        await conn.execute(f"""
            UPDATE {self.table_name}
            SET
                last_used = CURRENT_TIMESTAMP,
                use_count = use_count + 1
            WHERE id = $1
        """, cache_id)

    async def save_query_cache(
        self,
        query_text: str,
        query_embedding: List[float],
        sql_query: str,
        identity: str,
        genie_space_id: str
    ) -> int:
        """Save a new query to the cache."""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        embedding_array = np.array(query_embedding, dtype=np.float32)

        async with self.pool.acquire() as conn:
            await register_vector(conn)

            row = await conn.fetchrow(f"""
                INSERT INTO {self.table_name}
                (query_text, query_embedding, sql_query, identity, genie_space_id,
                 created_at, last_used, use_count)
                VALUES ($1, $2::vector, $3, $4, $5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)
                RETURNING id
            """, query_text, embedding_array, sql_query, identity, genie_space_id)

            cache_id = row['id']
            logger.info("Saved to cache id=%d", cache_id)
            return cache_id

    async def get_all_cached_queries(
        self,
        identity: Optional[str] = None,
        genie_space_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get all cached queries (no TTL filtering - shows full history)."""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        async with self.pool.acquire() as conn:
            where_clauses = []
            params = []
            param_idx = 1

            if identity:
                where_clauses.append(f"identity = ${param_idx}")
                params.append(identity)
                param_idx += 1

            if genie_space_id:
                where_clauses.append(f"genie_space_id = ${param_idx}")
                params.append(genie_space_id)
                param_idx += 1

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            params.append(limit)

            query = f"""
                SELECT
                    id, query_text, sql_query, identity, genie_space_id,
                    created_at, last_used, use_count
                FROM {self.table_name}
                {where_sql}
                ORDER BY last_used DESC
                LIMIT ${param_idx}
            """

            rows = await conn.fetch(query, *params)

            return [
                {
                    'id': row['id'],
                    'query_text': row['query_text'],
                    'sql_query': row['sql_query'],
                    'identity': row['identity'],
                    'genie_space_id': row['genie_space_id'],
                    'created_at': _to_utc_iso(row['created_at']),
                    'last_used': _to_utc_iso(row['last_used']),
                    'use_count': row['use_count']
                }
                for row in rows
            ]

    async def get_cache_stats(self) -> Dict:
        """Get statistics about the cache"""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        async with self.pool.acquire() as conn:
            stats = await conn.fetchrow(f"""
                SELECT
                    COUNT(*) as total_queries,
                    COUNT(DISTINCT identity) as unique_identities,
                    COUNT(DISTINCT genie_space_id) as unique_spaces,
                    SUM(use_count) as total_uses,
                    AVG(use_count) as avg_uses_per_query,
                    MAX(last_used) as most_recent_use
                FROM {self.table_name}
            """)

            return dict(stats)

    async def close(self):
        """Close the connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("PGVector connection pool closed")

    async def save_query_log(
        self,
        query_id: str,
        query_text: str,
        identity: str,
        stage: str,
        from_cache: bool = False,
        genie_space_id: Optional[str] = None
    ) -> int:
        """Save a query log entry"""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                INSERT INTO {self.query_log_table_name}
                (query_id, query_text, identity, stage, from_cache, genie_space_id, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6,
                        CURRENT_TIMESTAMP AT TIME ZONE 'UTC',
                        CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
                ON CONFLICT (query_id)
                DO UPDATE SET
                    stage = EXCLUDED.stage,
                    from_cache = EXCLUDED.from_cache,
                    updated_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                RETURNING id
            """, query_id, query_text, identity, stage, from_cache, genie_space_id)

            return row['id']

    async def get_query_logs(
        self,
        identity: Optional[str] = None,
        limit: int = 50
    ) -> List[dict]:
        """Get query logs, optionally filtered by identity"""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        async with self.pool.acquire() as conn:
            if identity:
                query = f"""
                    SELECT query_id, query_text, identity, stage, genie_space_id,
                           from_cache, created_at, updated_at
                    FROM {self.query_log_table_name}
                    WHERE identity = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                """
                rows = await conn.fetch(query, identity, limit)
            else:
                query = f"""
                    SELECT query_id, query_text, identity, stage, genie_space_id,
                           from_cache, created_at, updated_at
                    FROM {self.query_log_table_name}
                    ORDER BY created_at DESC
                    LIMIT $1
                """
                rows = await conn.fetch(query, limit)

            return [
                {
                    'query_id': row['query_id'],
                    'query_text': row['query_text'],
                    'identity': row['identity'],
                    'stage': row['stage'],
                    'genie_space_id': row['genie_space_id'],
                    'from_cache': row['from_cache'],
                    'created_at': _to_utc_iso(row['created_at']),
                    'updated_at': _to_utc_iso(row['updated_at'])
                }
                for row in rows
            ]
