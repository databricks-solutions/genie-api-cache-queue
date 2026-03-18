"""
Dynamic storage service that can switch backends at runtime.
Useful for Databricks Apps where Lakebase config comes from frontend.
All public methods are async — PGVector operations are awaited directly.

On connection errors, the cached backend is invalidated and recreated from
scratch (new JWT, new pool) before retrying the operation.
"""

import asyncio
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
        self._creation_lock = asyncio.Lock()

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
        """Check if the JWT will expire soon (within 10 minutes)."""
        if cache_key not in self._token_expiry:
            return True
        return (self._token_expiry[cache_key] - time.time()) < 600

    async def _invalidate_backend(self, runtime_settings):
        """Close and evict the cached backend under lock to avoid concurrent invalidation."""
        async with self._creation_lock:
            cache_key = self._get_cache_key(runtime_settings)
            old = self._pgvector_backends.pop(cache_key, None)
            self._token_expiry.pop(cache_key, None)
        if old and hasattr(old, 'close'):
            try:
                await old.close()
            except Exception:
                pass
        logger.info("Lakebase backend invalidated — will reconnect on next call")

    async def _get_or_create_pgvector_backend(self, runtime_settings):
        """Get or create a PGVector backend. Only one coroutine creates at a time."""
        cache_key = self._get_cache_key(runtime_settings)

        # Fast path: backend exists and is fresh — no lock needed
        if cache_key in self._pgvector_backends and not self._is_token_expired(cache_key):
            return self._pgvector_backends[cache_key]

        # Slow path: need to create or refresh — serialize with lock so only
        # one coroutine initializes the pool at a time.
        async with self._creation_lock:
            # Re-check: another coroutine may have already created it while we waited
            if cache_key in self._pgvector_backends and not self._is_token_expired(cache_key):
                return self._pgvector_backends[cache_key]

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

            from app.config import get_settings
            from app.api.config_store import get_effective_setting
            _s = get_settings()

            # Lakebase connections MUST use the Service Principal token.
            # No fallback to user PAT or env token — those users won't have Lakebase access.
            sp_token = get_effective_setting("lakebase_service_token")
            if not sp_token:
                raise ValueError(
                    "Lakebase requires a Service Principal token. "
                    "Configure 'Lakebase Service Token' (client_id:client_secret) in Settings."
                )
            effective_token = sp_token

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
            self._token_expiry[cache_key] = time.time() + 3000
            logger.info("Lakebase connection initialized")
            return backend

    async def refresh_default_backend(self):
        """Refresh the default Lakebase backend by re-initializing."""
        cache_key = self._DEFAULT_KEY
        if cache_key not in self._pgvector_backends:
            return
        if not self._is_token_expired(cache_key):
            return

        logger.info("Refreshing default Lakebase backend")
        try:
            from app.config import get_settings
            from app.services.storage_pgvector import PGVectorStorageService

            settings = get_settings()

            old = self._pgvector_backends.pop(cache_key, None)
            if old and hasattr(old, 'close'):
                try:
                    await old.close()
                except Exception:
                    pass

            from app.auth import get_service_principal_token
            token = settings.databricks_token or get_service_principal_token()

            new_backend = PGVectorStorageService(
                connection_string=settings.postgres_connection_string,
                table_name=settings.full_table_name,
                cache_ttl_hours=settings.cache_ttl_hours,
                databricks_pat=token,
                databricks_host=settings.databricks_host,
                lakebase_instance_name=settings.lakebase_instance,
            )
            await new_backend.initialize()
            self._pgvector_backends[cache_key] = new_backend
            self._token_expiry[cache_key] = time.time() + 3000
            self.default_backend = new_backend
            logger.info("Default backend refreshed")
        except Exception:
            logger.exception("Failed to refresh default backend")

    async def _resolve_backend(self, runtime_settings):
        """Resolve which backend to use, initializing lazily if needed.
        When Lakebase is configured, it MUST use the SP token — no fallback to local."""
        if not runtime_settings:
            return self.default_backend
        if hasattr(runtime_settings, 'runtime') and runtime_settings.runtime:
            rt = runtime_settings.runtime
            if rt.storage_backend == 'lakebase':
                from app.api.config_store import get_effective_setting
                sp_token = get_effective_setting("lakebase_service_token")
                if not rt.lakebase_instance_name:
                    raise ValueError("Lakebase requires 'Lakebase Instance Name' in Settings.")
                if not sp_token:
                    raise ValueError(
                        "Lakebase requires a Service Principal token. "
                        "Configure 'Lakebase Service Token' (client_id:client_secret) in Settings."
                    )
                return await self._get_or_create_pgvector_backend(runtime_settings)
            if rt.storage_backend == 'local':
                return self.default_backend
        return self.default_backend

    async def _with_reconnect(self, operation, runtime_settings):
        """Run operation. On any Lakebase error, invalidate backend and retry once.
        Safe: only retries once, only for PGVector backends, and creates a fresh pool."""
        try:
            return await operation()
        except Exception as first_err:
            cache_key = self._get_cache_key(runtime_settings)
            if cache_key not in self._pgvector_backends:
                raise
            logger.warning("Lakebase error: %s (%s) — reconnecting",
                          type(first_err).__name__, first_err)
            await self._invalidate_backend(runtime_settings)
            return await operation()

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
        async def _op():
            backend = await self._resolve_backend(runtime_settings)
            ttl = runtime_settings.cache_ttl_hours if runtime_settings and hasattr(runtime_settings, 'cache_ttl_hours') else None
            if hasattr(backend, 'pool'):
                return await backend.search_similar_query(
                    query_embedding, identity, threshold, genie_space_id,
                    cache_ttl_hours=ttl, shared_cache=shared_cache
                )
            return backend.search_similar_query(
                query_embedding, identity, threshold,
                genie_space_id=genie_space_id,
                cache_ttl_hours=ttl, shared_cache=shared_cache
            )
        return await self._with_reconnect(_op, runtime_settings)

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
        async def _op():
            backend = await self._resolve_backend(runtime_settings)
            if hasattr(backend, 'pool'):
                return await backend.save_query_cache(
                    query_text, query_embedding, sql_query, identity, genie_space_id
                )
            return backend.save_query_cache(
                query_text, query_embedding, sql_query, identity, genie_space_id
            )
        return await self._with_reconnect(_op, runtime_settings)

    async def get_all_cached_queries(
        self,
        identity: Optional[str] = None,
        runtime_settings=None
    ) -> List[dict]:
        """Get all cached queries."""
        async def _op():
            backend = await self._resolve_backend(runtime_settings)
            if hasattr(backend, 'pool'):
                return await backend.get_all_cached_queries(identity)
            return backend.get_all_cached_queries(identity)
        return await self._with_reconnect(_op, runtime_settings)

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
        async def _op():
            backend = await self._resolve_backend(runtime_settings)
            if hasattr(backend, 'pool'):
                return await backend.save_query_log(
                    query_id, query_text, identity, stage, from_cache, genie_space_id
                )
            return None
        try:
            return await self._with_reconnect(_op, runtime_settings)
        except Exception as e:
            logger.warning("save_query_log failed: %s", e)
            return None

    async def get_query_logs(
        self,
        identity: Optional[str] = None,
        limit: int = 50,
        runtime_settings=None
    ) -> List[dict]:
        """Get query logs."""
        async def _op():
            backend = await self._resolve_backend(runtime_settings)
            if hasattr(backend, 'pool'):
                return await backend.get_query_logs(identity, limit)
            return []
        try:
            return await self._with_reconnect(_op, runtime_settings)
        except Exception as e:
            logger.warning("get_query_logs failed: %s", e)
            return []

    async def get_cache_count(self, runtime_settings=None):
        """Return cache entry counts grouped by genie_space_id."""
        async def _op():
            backend = await self._resolve_backend(runtime_settings)
            if hasattr(backend, 'get_cache_count'):
                return await backend.get_cache_count()
            return {"total": 0, "by_space": {}}
        return await self._with_reconnect(_op, runtime_settings)

    async def clear_cache(self, runtime_settings=None, genie_space_id=None) -> int:
        """Delete cached queries, optionally filtered by genie_space_id."""
        async def _op():
            backend = await self._resolve_backend(runtime_settings)
            if hasattr(backend, 'clear_cache'):
                return await backend.clear_cache(genie_space_id=genie_space_id)
            return 0
        return await self._with_reconnect(_op, runtime_settings)
