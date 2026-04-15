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
        self.jwt_expires_at = 0  # epoch timestamp when the current JWT expires
        # All tables must live in the same schema as the cache table
        schema_prefix = self.table_name.rsplit('.', 1)[0] if '.' in self.table_name else 'public'
        self.schema_name = schema_prefix
        self.gateway_table_name = f"{schema_prefix}.gateway_configs"
        self.query_log_table_name = f"{schema_prefix}.{self.query_log_table_name.rsplit('.', 1)[-1]}"

    def _normalize_table_name(self, table_name: str) -> str:
        """Convert Databricks catalog.schema.table to PostgreSQL schema.table format."""
        table_parts = table_name.split('.')
        if len(table_parts) == 3:
            return f"{table_parts[1]}.{table_parts[2]}"
        elif len(table_parts) == 2:
            return table_name
        else:
            return f"public.{table_name}"

    def is_token_expiring_soon(self, buffer_seconds: int = 600) -> bool:
        """Check if the Lakebase JWT will expire within buffer_seconds."""
        if self.jwt_expires_at == 0:
            return False  # no JWT tracking (non-Lakebase or unknown TTL)
        import time
        return (self.jwt_expires_at - time.time()) < buffer_seconds

    async def reinitialize(self):
        """Generate a fresh JWT and create a new connection pool.
        Atomic swap: new pool is created before old pool is closed."""
        old_pool = self.pool
        logger.info("Reinitializing Lakebase pool (JWT expiring soon)")
        await self.initialize()
        if old_pool and old_pool is not self.pool:
            try:
                await old_pool.close()
            except Exception:
                pass

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
                    hostname, endpoint_name = self._resolve_autoscaling_endpoint(project_id)
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
            if self.schema_name != 'public':
                safe_schema = self.schema_name.replace('"', '""')
                try:
                    await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{safe_schema}"')
                    logger.info("Ensured schema '%s' exists", self.schema_name)
                except Exception as e:
                    logger.warning("Schema creation skipped (may require manual CREATE): %s", e)
            await self._ensure_extension(conn)
            await register_vector(conn)
            await self._ensure_table(conn)
            await self._ensure_query_log_table(conn)
            await self._ensure_gateway_table(conn)
            await self._migrate_genie_space_id_columns(conn)
            await self._migrate_original_query_text(conn)
            await self._migrate_caching_enabled(conn)

    async def _migrate_genie_space_id_columns(self, conn):
        """Migration: ensure both gateway_id and genie_space_id columns exist.
        gateway_id = external identifier (UUID) used for all operations.
        genie_space_id = internal Genie space ID, kept for audit/reference.
        """
        for table in [self.table_name, self.query_log_table_name]:
            parts = table.split(".")
            tbl = parts[-1]
            schema = parts[-2] if len(parts) >= 2 else "public"

            # Add gateway_id if missing (may have been renamed from genie_space_id)
            has_gw_col = await conn.fetchval(
                "SELECT 1 FROM information_schema.columns WHERE table_schema=$1 AND table_name=$2 AND column_name='gateway_id'",
                schema, tbl
            )
            if not has_gw_col:
                # Check if old column still exists — if so, rename it
                has_old = await conn.fetchval(
                    "SELECT 1 FROM information_schema.columns WHERE table_schema=$1 AND table_name=$2 AND column_name='genie_space_id'",
                    schema, tbl
                )
                if has_old:
                    try:
                        await conn.execute(f'ALTER TABLE {table} RENAME COLUMN genie_space_id TO gateway_id')
                        logger.info("Migrated %s: genie_space_id → gateway_id", table)
                    except Exception as e:
                        logger.warning("Rename failed for %s (may need ADD instead): %s", table, e)
                        try:
                            await conn.execute(f'ALTER TABLE {table} ADD COLUMN gateway_id VARCHAR(255)')
                            logger.info("Added gateway_id column to %s", table)
                        except Exception as e2:
                            logger.warning("ADD COLUMN also failed for %s: %s", table, e2)
                else:
                    try:
                        await conn.execute(f'ALTER TABLE {table} ADD COLUMN gateway_id VARCHAR(255)')
                        logger.info("Added gateway_id column to %s", table)
                    except Exception as e:
                        logger.warning("Could not add gateway_id to %s: %s", table, e)

            # Add genie_space_id back as audit column if missing
            has_audit_col = await conn.fetchval(
                "SELECT 1 FROM information_schema.columns WHERE table_schema=$1 AND table_name=$2 AND column_name='genie_space_id'",
                schema, tbl
            )
            if not has_audit_col:
                try:
                    await conn.execute(f'ALTER TABLE {table} ADD COLUMN genie_space_id VARCHAR(255)')
                    logger.info("Added audit genie_space_id column to %s", table)
                except Exception as e:
                    logger.warning("Could not add genie_space_id to %s: %s", table, e)

    async def _migrate_original_query_text(self, conn):
        """Migration: add original_query_text column to cached_queries if missing."""
        try:
            parts = self.table_name.split('.')
            schema = parts[-2] if len(parts) >= 2 else 'public'
            tbl = parts[-1]
            exists = await conn.fetchval(
                "SELECT 1 FROM information_schema.columns WHERE table_schema=$1 AND table_name=$2 AND column_name='original_query_text'",
                schema, tbl
            )
            if not exists:
                await conn.execute(f'ALTER TABLE {self.table_name} ADD COLUMN original_query_text TEXT')
                logger.info("Added original_query_text column to %s", self.table_name)
        except Exception as e:
            logger.warning("Could not add original_query_text to %s: %s", self.table_name, e)

    async def _migrate_caching_enabled(self, conn):
        """Migration: add caching_enabled column to gateway_configs if missing."""
        try:
            parts = self.gateway_table_name.split('.')
            schema = parts[-2] if len(parts) >= 2 else 'public'
            tbl = parts[-1]
            exists = await conn.fetchval(
                "SELECT 1 FROM information_schema.columns WHERE table_schema=$1 AND table_name=$2 AND column_name='caching_enabled'",
                schema, tbl
            )
            if not exists:
                await conn.execute(f'ALTER TABLE {self.gateway_table_name} ADD COLUMN caching_enabled BOOLEAN DEFAULT true')
                logger.info("Added caching_enabled column to %s", self.gateway_table_name)
        except Exception as e:
            logger.warning("Could not add caching_enabled to %s: %s", self.gateway_table_name, e)

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

        Inside Databricks Apps: uses the app's built-in SP, auto-detected from
        DATABRICKS_CLIENT_ID/SECRET env vars. The caller's proxy token
        (X-Forwarded-Access-Token) is NOT used for Lakebase.

        Local development: uses the lakebase_service_token from Settings
        (either SP client_id:client_secret or PAT).

        The SP must have CAN_MANAGE on the Lakebase project and a PostgreSQL
        role created via databricks_create_role(). When using a custom schema
        (LAKEBASE_SCHEMA != 'public'), the SP also needs CREATE privilege on
        the database for auto-creation of the schema.
        """
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.core import Config
        import os

        # Inside Databricks Apps: use the app's built-in SP (env vars auto-detected)
        if os.getenv("DATABRICKS_CLIENT_ID"):
            logger.info("Lakebase auth: app built-in SP (DATABRICKS_CLIENT_ID)")
            return WorkspaceClient()

        # Local dev: use the configured lakebase_service_token
        token = self.databricks_pat or ""
        if ":" in token and not token.startswith("dapi") and not token.startswith("eyJ"):
            client_id, client_secret = token.split(":", 1)
            logger.info("Lakebase auth: SP OAuth (client_id=%s...)", client_id[:12])
            config = Config(
                host=self.databricks_host,
                client_id=client_id,
                client_secret=client_secret,
                auth_type="oauth-m2m",
            )
            return WorkspaceClient(config=config)
        elif token:
            logger.info("Lakebase auth: PAT")
            config = Config(
                host=self.databricks_host,
                token=token,
                auth_type="pat",
            )
            return WorkspaceClient(config=config)
        else:
            raise ValueError(
                "No Lakebase credentials available. "
                "Ensure the app's SP has CAN_MANAGE on the Lakebase project."
            )

    def _resolve_autoscaling_endpoint(self, project_id: str) -> tuple:
        """Resolve Lakebase Autoscaling project to (hostname, endpoint_name)."""
        client = self._get_lakebase_sdk_client()
        endpoints = client.api_client.do(
            'GET',
            f'/api/2.0/postgres/projects/{project_id}/branches/production/endpoints'
        )
        eps = endpoints.get("endpoints", [])
        if not eps:
            raise ValueError(f"No endpoints found for Autoscaling project '{project_id}'")
        ep = eps[0]
        return ep["status"]["hosts"]["host"], ep["name"]

    def _build_autoscaling_connection_string(self, hostname: str, endpoint_name: str, quote_plus) -> str:
        """Generate JWT credential for Autoscaling Lakebase and build connection string."""
        import time
        client = self._get_lakebase_sdk_client()
        cred = client.postgres.generate_database_credential(endpoint=endpoint_name)
        username = client.current_user.me().user_name

        expires_in = getattr(cred, 'expires_in', None) or 3600
        self.jwt_expires_at = time.time() + expires_in
        logger.info("Autoscaling JWT generated for %s (expires_in=%ds)", username, expires_in)

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
        """Create the cached_queries table and indexes.
        Index creation is best-effort — skipped if the current role lacks ownership."""
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id SERIAL PRIMARY KEY,
                query_text TEXT NOT NULL,
                original_query_text TEXT,
                query_embedding vector(1024),
                sql_query TEXT NOT NULL,
                identity VARCHAR(255) NOT NULL,
                gateway_id VARCHAR(255) NOT NULL,
                created_at TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                last_used TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                use_count INTEGER DEFAULT 1
            )
        """)

        idx_base = self.table_name.replace('.', '_')
        for idx_sql in [
            f"CREATE INDEX IF NOT EXISTS {idx_base}_embedding_idx ON {self.table_name} USING ivfflat (query_embedding vector_cosine_ops) WITH (lists = 100)",
            f"CREATE INDEX IF NOT EXISTS {idx_base}_identity_idx ON {self.table_name} (identity)",
            f"CREATE INDEX IF NOT EXISTS {idx_base}_space_idx ON {self.table_name} (gateway_id)",
        ]:
            try:
                await conn.execute(idx_sql)
            except Exception as e:
                logger.warning("Index creation skipped: %s", e)

        logger.info("PGVector table '%s' initialized", self.table_name)

    async def _ensure_query_log_table(self, conn):
        """Create the query_logs table and indexes.
        Index creation is best-effort — skipped if the current role lacks ownership."""
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.query_log_table_name} (
                id SERIAL PRIMARY KEY,
                query_id VARCHAR(255) NOT NULL UNIQUE,
                query_text TEXT NOT NULL,
                identity VARCHAR(255) NOT NULL,
                stage VARCHAR(50) NOT NULL,
                gateway_id VARCHAR(255),
                from_cache BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                updated_at TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
            )
        """)

        log_idx_base = self.query_log_table_name.replace('.', '_')
        for idx_sql in [
            f"CREATE INDEX IF NOT EXISTS {log_idx_base}_identity_idx ON {self.query_log_table_name} (identity)",
            f"CREATE INDEX IF NOT EXISTS {log_idx_base}_created_idx ON {self.query_log_table_name} (created_at DESC)",
        ]:
            try:
                await conn.execute(idx_sql)
            except Exception as e:
                logger.warning("Index creation skipped: %s", e)

        logger.info("Query log table '%s' initialized", self.query_log_table_name)

    async def _ensure_gateway_table(self, conn):
        """Create the gateway_configs table if it does not exist."""
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.gateway_table_name} (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                genie_space_id TEXT NOT NULL,
                sql_warehouse_id TEXT NOT NULL,
                similarity_threshold FLOAT DEFAULT 0.92,
                max_queries_per_minute INT DEFAULT 5,
                cache_ttl_hours FLOAT DEFAULT 24,
                question_normalization_enabled BOOLEAN DEFAULT true,
                cache_validation_enabled BOOLEAN DEFAULT true,
                caching_enabled BOOLEAN DEFAULT true,
                embedding_provider TEXT DEFAULT 'databricks',
                databricks_embedding_endpoint TEXT DEFAULT 'databricks-gte-large-en',
                shared_cache BOOLEAN DEFAULT true,
                status TEXT DEFAULT 'active',
                created_by TEXT,
                description TEXT DEFAULT '',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        logger.info("Gateway table '%s' initialized", self.gateway_table_name)

    async def search_similar_query(
        self,
        query_embedding: List[float],
        identity: str,
        threshold: float = 0.92,
        gateway_id: Optional[str] = None,
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

            if gateway_id:
                filters.append(f"gateway_id = ${param_idx}")
                params.append(gateway_id)
                param_idx += 1

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
                    original_query_text,
                    sql_query,
                    1 - (query_embedding <=> $1::vector) AS similarity
                FROM {self.table_name}
                WHERE {where_clause}
                ORDER BY query_embedding <=> $1::vector
                LIMIT 1
            """

            logger.info("Cache search: table=%s threshold=%.2f ttl=%s shared=%s space=%s filters=%d SQL: %s params_count=%d",
                        self.table_name, threshold, ttl or "unlimited", shared_cache,
                        gateway_id or "any", len(filters), where_clause[:200], len(params))

            row = await conn.fetchrow(query, *params)

            if row:
                await self._update_usage(conn, row['id'])
                logger.info("Cache HIT id=%s similarity=%.3f query=%s", row['id'], row['similarity'], row['query_text'][:50])
                return (row['id'], row['query_text'], row['sql_query'], float(row['similarity']), row['original_query_text'])

            # Log closest available match for diagnostics
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
        gateway_id: str,
        original_query_text: str = None,
        genie_space_id: str = None,  # audit/reference only
    ) -> int:
        """Save a new query to the cache."""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        embedding_array = np.array(query_embedding, dtype=np.float32)

        async with self.pool.acquire() as conn:
            await register_vector(conn)

            row = await conn.fetchrow(f"""
                INSERT INTO {self.table_name}
                (query_text, original_query_text, query_embedding, sql_query, identity, gateway_id, genie_space_id,
                 created_at, last_used, use_count)
                VALUES ($1, $2, $3::vector, $4, $5, $6, $7, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)
                RETURNING id
            """, query_text, original_query_text, embedding_array, sql_query, identity, gateway_id, genie_space_id)

            cache_id = row['id']
            logger.info("Saved to cache id=%d", cache_id)
            return cache_id

    async def get_all_cached_queries(
        self,
        identity: Optional[str] = None,
        gateway_id: Optional[str] = None,
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

            if gateway_id:
                where_clauses.append(f"gateway_id = ${param_idx}")
                params.append(gateway_id)
                param_idx += 1

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            params.append(limit)

            query = f"""
                SELECT
                    id, query_text, sql_query, identity, gateway_id,
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
                    'gateway_id': row['gateway_id'],
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
                    COUNT(DISTINCT gateway_id) as unique_spaces,
                    SUM(use_count) as total_uses,
                    AVG(use_count) as avg_uses_per_query,
                    MAX(last_used) as most_recent_use
                FROM {self.table_name}
            """)

            return dict(stats)

    async def get_cache_count(self):
        """Return cache entry counts grouped by gateway_id."""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized.")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT COALESCE(gateway_id, 'unknown') as space_id, COUNT(*) as count
                FROM {self.table_name}
                GROUP BY gateway_id
            """)
            total = sum(r['count'] for r in rows)
            by_space = {r['space_id']: r['count'] for r in rows}
            return {"total": total, "by_space": by_space}

    async def clear_cache(self, gateway_id=None):
        """Delete cached queries, optionally filtered by gateway_id."""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized.")
        async with self.pool.acquire() as conn:
            if gateway_id:
                count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {self.table_name} WHERE gateway_id = $1", gateway_id
                )
                await conn.execute(
                    f"DELETE FROM {self.table_name} WHERE gateway_id = $1", gateway_id
                )
                logger.info("Cache cleared for space %s: %d entries deleted from %s", gateway_id, count, self.table_name)
            else:
                count = await conn.fetchval(f"SELECT COUNT(*) FROM {self.table_name}")
                await conn.execute(f"DELETE FROM {self.table_name}")
                logger.info("Cache cleared: %d entries deleted from %s", count, self.table_name)
            return count

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
        gateway_id: Optional[str] = None,
        genie_space_id: Optional[str] = None,  # audit/reference only
    ) -> int:
        """Save a query log entry"""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                INSERT INTO {self.query_log_table_name}
                (query_id, query_text, identity, stage, from_cache, gateway_id, genie_space_id, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7,
                        CURRENT_TIMESTAMP AT TIME ZONE 'UTC',
                        CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
                ON CONFLICT (query_id)
                DO UPDATE SET
                    stage = EXCLUDED.stage,
                    from_cache = EXCLUDED.from_cache,
                    gateway_id = COALESCE(EXCLUDED.gateway_id, {self.query_log_table_name}.gateway_id),
                    genie_space_id = COALESCE(EXCLUDED.genie_space_id, {self.query_log_table_name}.genie_space_id),
                    updated_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                RETURNING id
            """, query_id, query_text, identity, stage, from_cache, gateway_id, genie_space_id)

            return row['id']

    async def get_query_logs(
        self,
        identity: Optional[str] = None,
        limit: int = 50,
        gateway_id: Optional[str] = None,
    ) -> List[dict]:
        """Get query logs, optionally filtered by identity and/or gateway_id."""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        async with self.pool.acquire() as conn:
            filters = []
            params: list = []
            if identity:
                params.append(identity)
                filters.append(f"identity = ${len(params)}")
            if gateway_id:
                params.append(gateway_id)
                filters.append(f"gateway_id = ${len(params)}")
            where = f"WHERE {' AND '.join(filters)}" if filters else ""
            params.append(limit)
            query = f"""
                SELECT query_id, query_text, identity, stage, gateway_id,
                       from_cache, created_at, updated_at
                FROM {self.query_log_table_name}
                {where}
                ORDER BY created_at DESC
                LIMIT ${len(params)}
            """
            rows = await conn.fetch(query, *params)

            return [
                {
                    'query_id': row['query_id'],
                    'query_text': row['query_text'],
                    'identity': row['identity'],
                    'stage': row['stage'],
                    'gateway_id': row['gateway_id'],
                    'from_cache': row['from_cache'],
                    'created_at': _to_utc_iso(row['created_at']),
                    'updated_at': _to_utc_iso(row['updated_at'])
                }
                for row in rows
            ]

    # --- Gateway CRUD ---

    async def create_gateway(self, config: dict) -> dict:
        """Create a new gateway configuration."""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        async with self.pool.acquire() as conn:
            await conn.execute(f"""
                INSERT INTO {self.gateway_table_name}
                (id, name, genie_space_id, sql_warehouse_id, similarity_threshold,
                 max_queries_per_minute, cache_ttl_hours, question_normalization_enabled,
                 cache_validation_enabled, caching_enabled, embedding_provider, databricks_embedding_endpoint,
                 shared_cache, status, created_by, description, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
            """,
                config["id"], config["name"], config["genie_space_id"], config["sql_warehouse_id"],
                config.get("similarity_threshold", 0.92), config.get("max_queries_per_minute", 5),
                config.get("cache_ttl_hours", 24), config.get("question_normalization_enabled", True),
                config.get("cache_validation_enabled", True), config.get("caching_enabled", True),
                config.get("embedding_provider", "databricks"),
                config.get("databricks_embedding_endpoint", "databricks-gte-large-en"),
                config.get("shared_cache", True), config.get("status", "active"),
                config.get("created_by"), config.get("description", ""),
                config.get("created_at"), config.get("updated_at"),
            )
            logger.info("Gateway created in DB: id=%s name=%s", config["id"], config["name"])
            return config

    async def get_gateway(self, gateway_id: str) -> Optional[dict]:
        """Get a gateway configuration by ID."""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                SELECT id, name, genie_space_id, sql_warehouse_id, similarity_threshold,
                       max_queries_per_minute, cache_ttl_hours, question_normalization_enabled,
                       cache_validation_enabled, caching_enabled, embedding_provider, databricks_embedding_endpoint,
                       shared_cache, status, created_by, description, created_at, updated_at
                FROM {self.gateway_table_name}
                WHERE id = $1
            """, gateway_id)

            if not row:
                return None
            return self._row_to_gateway_dict(row)

    async def list_gateways(self) -> list:
        """List all gateway configurations."""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT id, name, genie_space_id, sql_warehouse_id, similarity_threshold,
                       max_queries_per_minute, cache_ttl_hours, question_normalization_enabled,
                       cache_validation_enabled, caching_enabled, embedding_provider, databricks_embedding_endpoint,
                       shared_cache, status, created_by, description, created_at, updated_at
                FROM {self.gateway_table_name}
                ORDER BY created_at DESC
            """)
            return [self._row_to_gateway_dict(row) for row in rows]

    async def update_gateway(self, gateway_id: str, updates: dict) -> Optional[dict]:
        """Update a gateway configuration."""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        # Build dynamic SET clause from provided updates
        allowed_fields = {
            "name", "similarity_threshold", "max_queries_per_minute", "cache_ttl_hours",
            "question_normalization_enabled", "cache_validation_enabled", "caching_enabled",
            "embedding_provider", "databricks_embedding_endpoint", "shared_cache", "status", "description",
            "sql_warehouse_id", "genie_space_id",
        }
        set_parts = []
        params = []
        param_idx = 1
        for key, value in updates.items():
            if key in allowed_fields and value is not None:
                set_parts.append(f"{key} = ${param_idx}")
                params.append(value)
                param_idx += 1

        if not set_parts:
            return await self.get_gateway(gateway_id)

        set_parts.append(f"updated_at = NOW()")
        params.append(gateway_id)

        async with self.pool.acquire() as conn:
            result = await conn.execute(f"""
                UPDATE {self.gateway_table_name}
                SET {', '.join(set_parts)}
                WHERE id = ${param_idx}
            """, *params)

            if result == "UPDATE 0":
                return None

            logger.info("Gateway updated in DB: id=%s fields=%s", gateway_id, list(updates.keys()))
            return await self.get_gateway(gateway_id)

    async def delete_gateway(self, gateway_id: str) -> bool:
        """Delete a gateway configuration."""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        async with self.pool.acquire() as conn:
            result = await conn.execute(f"""
                DELETE FROM {self.gateway_table_name} WHERE id = $1
            """, gateway_id)
            deleted = result != "DELETE 0"
            if deleted:
                logger.info("Gateway deleted from DB: id=%s", gateway_id)
            return deleted

    async def get_gateway_stats(self, gateway_id: str) -> dict:
        """Get cache and query stats for a gateway."""
        if not self.pool:
            raise RuntimeError("PGVector storage not initialized. Call initialize() first.")

        gw = await self.get_gateway(gateway_id)
        if not gw:
            return {"cache_count": 0, "query_count_7d": 0}

        space_id = gw.get("genie_space_id")  # internal Genie space ID for reference
        async with self.pool.acquire() as conn:
            # All cache ops use gateway_id as namespace key
            cache_count = await conn.fetchval(f"""
                SELECT COUNT(*) FROM {self.table_name}
                WHERE gateway_id = $1
            """, gateway_id) or 0

            query_count = await conn.fetchval(f"""
                SELECT COUNT(*) FROM {self.query_log_table_name}
                WHERE gateway_id = $1
                  AND created_at > NOW() - INTERVAL '7 days'
            """, gateway_id) or 0

            cache_hits = await conn.fetchval(f"""
                SELECT COUNT(*) FROM {self.query_log_table_name}
                WHERE gateway_id = $1
                  AND from_cache = true
                  AND created_at > NOW() - INTERVAL '7 days'
            """, gateway_id) or 0

            return {"cache_count": cache_count, "query_count_7d": query_count, "cache_hits_7d": cache_hits}

    def _row_to_gateway_dict(self, row) -> dict:
        """Convert a database row to a gateway dict."""
        return {
            "id": row["id"],
            "name": row["name"],
            "genie_space_id": row["genie_space_id"],
            "sql_warehouse_id": row["sql_warehouse_id"],
            "similarity_threshold": row["similarity_threshold"],
            "max_queries_per_minute": row["max_queries_per_minute"],
            "cache_ttl_hours": row["cache_ttl_hours"],
            "question_normalization_enabled": row["question_normalization_enabled"],
            "cache_validation_enabled": row["cache_validation_enabled"],
            "caching_enabled": row["caching_enabled"] if "caching_enabled" in row.keys() else True,
            "embedding_provider": row["embedding_provider"],
            "databricks_embedding_endpoint": row["databricks_embedding_endpoint"],
            "shared_cache": row["shared_cache"],
            "status": row["status"],
            "created_by": row["created_by"],
            "description": row["description"],
            "created_at": _to_utc_iso(row["created_at"]),
            "updated_at": _to_utc_iso(row["updated_at"]),
        }
