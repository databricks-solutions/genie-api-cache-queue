"""
Dynamic storage service that can switch backends at runtime.
Useful for Databricks Apps where Lakebase config comes from frontend.
All public methods are async — PGVector operations are awaited directly.
"""

import logging
import time
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


class DynamicStorageService:
    """
    Storage service that dynamically selects backend based on runtime config.
    Falls back to default backend when no runtime config is provided.
    """

    _DEFAULT_KEY = "__default__"

    def __init__(self, default_backend):
        self.default_backend = default_backend
        self._pgvector_backends = {}
        self._token_expiry = {}

    def _get_cache_key(self, runtime_settings):
        """Generate cache key for backend pool reuse."""
        if not runtime_settings or not hasattr(runtime_settings, 'runtime') or not runtime_settings.runtime:
            return self._DEFAULT_KEY
        if runtime_settings.runtime.storage_backend != 'lakebase':
            return self._DEFAULT_KEY
        if self._DEFAULT_KEY in self._pgvector_backends:
            return self._DEFAULT_KEY
        instance = runtime_settings.runtime.lakebase_instance_name
        table = runtime_settings.full_table_name
        if instance and table:
            return f"{instance}:{table}"
        return self._DEFAULT_KEY

    def _is_token_expired(self, cache_key):
        """Check if OAuth token is expired or will expire soon (within 5 minutes)."""
        if cache_key not in self._token_expiry:
            return True
        return (self._token_expiry[cache_key] - time.time()) < 300

    async def _get_or_create_pgvector_backend(self, runtime_settings):
        """Get or create a PGVector backend. Awaits initialization directly."""
        cache_key = self._get_cache_key(runtime_settings)

        if cache_key in self._pgvector_backends and not self._is_token_expired(cache_key):
            return self._pgvector_backends[cache_key]

        # Expire old backend if token is stale
        if cache_key in self._pgvector_backends and self._is_token_expired(cache_key):
            old = self._pgvector_backends.pop(cache_key, None)
            if old and hasattr(old, 'close'):
                try:
                    await old.close()
                except Exception:
                    pass

        logger.info("Creating Lakebase connection: instance=%s table=%s",
                    runtime_settings.runtime.lakebase_instance_name,
                    runtime_settings.full_table_name)

        from app.services.storage_pgvector import PGVectorStorageService
        ttl = runtime_settings.cache_ttl_hours if hasattr(runtime_settings, 'cache_ttl_hours') else 24

        # For Lakebase operations, prefer user_pat (full API access) over user_token
        # (OAuth proxy token has limited scopes and can't access Postgres API)
        effective_token = ((runtime_settings.runtime.user_pat if runtime_settings.runtime else None) or
                           getattr(runtime_settings, 'user_token', None))

        backend = PGVectorStorageService(
            connection_string=runtime_settings.postgres_connection_string,
            table_name=runtime_settings.full_table_name,
            query_log_table_name=runtime_settings.query_log_table_name,
            databricks_pat=effective_token,
            databricks_host=runtime_settings.databricks_host,
            lakebase_instance_name=runtime_settings.runtime.lakebase_instance_name if runtime_settings.runtime else None,
            cache_ttl_hours=ttl
        )

        await backend.initialize()
        self._pgvector_backends[cache_key] = backend
        self._token_expiry[cache_key] = time.time() + 3300
        logger.info("Lakebase connection initialized (token valid ~55min)")
        return backend

    async def refresh_default_backend(self):
        """Refresh OAuth token for the default Lakebase backend. Called periodically."""
        cache_key = self._DEFAULT_KEY
        if cache_key not in self._pgvector_backends:
            return
        if not self._is_token_expired(cache_key):
            return

        logger.info("Refreshing OAuth token for default Lakebase backend")
        try:
            from app.config import get_settings
            from app.services.storage_pgvector import PGVectorStorageService
            from urllib.parse import quote_plus
            import uuid as _uuid
            import httpx

            settings = get_settings()

            # Use REST API for credential generation (works with both Provisioned and Autoscaling)
            async with httpx.AsyncClient() as http_client:
                cred_url = f"{settings.databricks_host}/api/2.0/database/credentials/generate"
                response = await http_client.post(
                    cred_url,
                    headers={"Authorization": f"Bearer {settings.databricks_token}"},
                    json={"request_id": str(_uuid.uuid4())}
                )
                response.raise_for_status()
                cred_data = response.json()
                oauth_token = cred_data.get("token")

            conn_string = (
                f"postgresql://{quote_plus(settings.postgres_user)}:{quote_plus(oauth_token)}"
                f"@{settings.lakebase_instance}:{settings.postgres_port}/databricks_postgres"
                f"?sslmode={settings.postgres_sslmode}"
            )

            old = self._pgvector_backends.pop(cache_key, None)
            if old and hasattr(old, 'close'):
                try:
                    await old.close()
                except Exception:
                    pass

            new_backend = PGVectorStorageService(
                connection_string=conn_string,
                table_name=settings.full_table_name,
                cache_ttl_hours=settings.cache_ttl_hours
            )
            await new_backend.initialize()
            self._pgvector_backends[cache_key] = new_backend
            self._token_expiry[cache_key] = time.time() + 3300
            self.default_backend = new_backend
            logger.info("Default backend OAuth token refreshed")
        except Exception:
            logger.exception("Failed to refresh default backend OAuth token")

    async def _resolve_backend(self, runtime_settings):
        """Resolve which backend to use, initializing lazily if needed."""
        if not runtime_settings:
            return self.default_backend
        if hasattr(runtime_settings, 'runtime') and runtime_settings.runtime:
            # Accept user_token (OAuth from Databricks Apps proxy) OR user_pat (from localStorage)
            has_token = (runtime_settings.runtime.user_pat or
                         getattr(runtime_settings, 'user_token', None))
            if (runtime_settings.runtime.storage_backend == 'lakebase' and
                    runtime_settings.runtime.lakebase_instance_name and
                    has_token):
                return await self._get_or_create_pgvector_backend(runtime_settings)
            if runtime_settings.runtime.storage_backend == 'local':
                return self.default_backend
        return self.default_backend

    async def search_similar_query(
        self,
        query_embedding: List[float],
        identity: str,
        threshold: float,
        genie_space_id: Optional[str] = None,
        runtime_settings=None,
        shared_cache: bool = True
    ) -> Optional[Tuple[int, str, str, float]]:
        """Search for similar cached queries using vector similarity."""
        backend = await self._resolve_backend(runtime_settings)
        ttl = runtime_settings.cache_ttl_hours if runtime_settings and hasattr(runtime_settings, 'cache_ttl_hours') else None

        if hasattr(backend, 'pool'):
            return await backend.search_similar_query(
                query_embedding, identity, threshold, genie_space_id,
                cache_ttl_hours=ttl, shared_cache=shared_cache
            )

        return backend.search_similar_query(
            query_embedding, identity, threshold,
            cache_ttl_hours=ttl, shared_cache=shared_cache
        )

    async def save_query_cache(
        self,
        query_text: str,
        query_embedding: List[float],
        sql_query: str,
        identity: str,
        genie_space_id: str,
        runtime_settings=None
    ) -> int:
        """Save a new query to the cache."""
        backend = await self._resolve_backend(runtime_settings)

        if hasattr(backend, 'pool'):
            return await backend.save_query_cache(
                query_text, query_embedding, sql_query, identity, genie_space_id
            )

        return backend.save_query_cache(
            query_text, query_embedding, sql_query, identity, genie_space_id
        )

    async def get_all_cached_queries(
        self,
        identity: Optional[str] = None,
        runtime_settings=None
    ) -> List[dict]:
        """Get all cached queries."""
        backend = await self._resolve_backend(runtime_settings)

        if hasattr(backend, 'pool'):
            return await backend.get_all_cached_queries(identity)

        return backend.get_all_cached_queries(identity)

    async def save_query_log(
        self,
        query_id: str,
        query_text: str,
        identity: str,
        stage: str,
        from_cache: bool = False,
        genie_space_id: Optional[str] = None,
        runtime_settings=None
    ) -> Optional[int]:
        """Save a query log entry."""
        backend = await self._resolve_backend(runtime_settings)

        if hasattr(backend, 'pool'):
            try:
                return await backend.save_query_log(
                    query_id, query_text, identity, stage, from_cache, genie_space_id
                )
            except Exception as e:
                logger.warning("save_query_log failed: %s", e)
                return None

        return None

    async def get_query_logs(
        self,
        identity: Optional[str] = None,
        limit: int = 50,
        runtime_settings=None
    ) -> List[dict]:
        """Get query logs."""
        backend = await self._resolve_backend(runtime_settings)

        if hasattr(backend, 'pool'):
            try:
                return await backend.get_query_logs(identity, limit)
            except Exception as e:
                logger.warning("get_query_logs failed: %s", e)
                return []

        return []
