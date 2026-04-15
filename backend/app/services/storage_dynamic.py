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


    async def _get_or_create_pgvector_backend(self, runtime_settings):
        """Get or create a PGVector backend. Only one coroutine creates at a time."""
        cache_key = self._get_cache_key(runtime_settings)

        # Fast path: backend exists
        if cache_key in self._pgvector_backends:
            return self._pgvector_backends[cache_key]

        # Slow path: create under lock
        async with self._creation_lock:
            if cache_key in self._pgvector_backends:
                return self._pgvector_backends[cache_key]

            logger.info("Creating Lakebase connection: instance=%s table=%s",
                        runtime_settings.runtime.lakebase_instance_name,
                        runtime_settings.full_table_name)

            from app.services.storage_pgvector import PGVectorStorageService
            from app.api.config_store import get_effective_setting
            from app.auth import get_service_principal_token

            ttl = runtime_settings.cache_ttl_hours if hasattr(runtime_settings, 'cache_ttl_hours') else 24
            sp_token = get_effective_setting("lakebase_service_token") or get_service_principal_token()
            if not sp_token:
                raise ValueError(
                    "Lakebase requires a Service Principal token. "
                    "Configure 'Lakebase Service Token' in Settings or ensure "
                    "DATABRICKS_CLIENT_ID/SECRET are set."
                )

            backend = PGVectorStorageService(
                connection_string=runtime_settings.postgres_connection_string,
                table_name=runtime_settings.full_table_name,
                query_log_table_name=runtime_settings.query_log_table_name,
                databricks_pat=sp_token,
                databricks_host=runtime_settings.databricks_host,
                lakebase_instance_name=runtime_settings.runtime.lakebase_instance_name if runtime_settings.runtime else None,
                cache_ttl_hours=ttl
            )

            await backend.initialize()
            self._pgvector_backends[cache_key] = backend
            logger.info("Lakebase connection initialized")
            return backend

    async def _proactive_refresh(self, backend):
        """Refresh a backend's JWT if it is expiring soon. Thread-safe via creation lock."""
        if not hasattr(backend, 'is_token_expiring_soon') or not backend.is_token_expiring_soon():
            return
        async with self._creation_lock:
            # Re-check after acquiring lock
            if not backend.is_token_expiring_soon():
                return
            logger.info("Proactively refreshing Lakebase JWT")
            await backend.reinitialize()

    async def _ensure_backend_healthy(self, backend):
        """Ensure backend pool is open and JWT is fresh."""
        if hasattr(backend, 'pool') and backend.pool is not None and backend.pool._closed:
            async with self._creation_lock:
                if backend.pool is not None and not backend.pool._closed:
                    return
                logger.warning("Lakebase pool is closed — reinitializing")
                await backend.reinitialize()
            return
        await self._proactive_refresh(backend)

    async def refresh_all_backends(self):
        """Proactively refresh all backends whose JWT is expiring soon. Called by background loop."""
        for cache_key, backend in list(self._pgvector_backends.items()):
            try:
                await self._proactive_refresh(backend)
            except Exception as e:
                logger.error("Background refresh failed for %s: %s", cache_key, e)
        # Also check default backend (may not be in _pgvector_backends)
        try:
            await self._proactive_refresh(self.default_backend)
        except Exception as e:
            logger.error("Background refresh failed for default backend: %s", e)

    async def _resolve_backend(self, runtime_settings):
        """Resolve which backend to use, initializing lazily if needed.
        Proactively refreshes JWT before it expires."""
        if not runtime_settings:
            await self._ensure_backend_healthy(self.default_backend)
            return self.default_backend
        if hasattr(runtime_settings, 'runtime') and runtime_settings.runtime:
            rt = runtime_settings.runtime
            if rt.storage_backend == 'lakebase':
                from app.api.config_store import get_effective_setting
                from app.auth import get_service_principal_token
                sp_token = get_effective_setting("lakebase_service_token") or get_service_principal_token()
                if not rt.lakebase_instance_name:
                    await self._ensure_backend_healthy(self.default_backend)
                    return self.default_backend
                if not sp_token:
                    raise ValueError(
                        "Lakebase requires a Service Principal token. "
                        "Configure 'Lakebase Service Token' in Settings or ensure "
                        "DATABRICKS_CLIENT_ID/SECRET are set."
                    )
                backend = await self._get_or_create_pgvector_backend(runtime_settings)
                await self._proactive_refresh(backend)
                return backend
            if rt.storage_backend == 'local':
                return self.default_backend
        return self.default_backend

    async def _with_reconnect(self, operation, runtime_settings):
        """Run operation. On any Lakebase error, reinitialize pool and retry once."""
        try:
            return await operation()
        except Exception as first_err:
            backend = await self._resolve_backend(runtime_settings)
            if not hasattr(backend, 'reinitialize'):
                raise
            logger.warning("Lakebase error: %s (%s) — reinitializing",
                          type(first_err).__name__, first_err)
            try:
                async with self._creation_lock:
                    await backend.reinitialize()
            except Exception as reinit_err:
                logger.error("Reinitialize failed: %s", reinit_err)
                raise first_err
            return await operation()

    async def search_similar_query(
        self,
        query_embedding: List[float],
        identity: str,
        threshold: float,
        gateway_id: Optional[str] = None,
        runtime_settings=None,
        shared_cache: bool = True
    ) -> Optional[Tuple[int, str, str, float]]:
        """Search for similar cached queries using vector similarity."""
        async def _op():
            backend = await self._resolve_backend(runtime_settings)
            ttl = runtime_settings.cache_ttl_hours if runtime_settings and hasattr(runtime_settings, 'cache_ttl_hours') else None
            if hasattr(backend, 'pool'):
                return await backend.search_similar_query(
                    query_embedding, identity, threshold, gateway_id,
                    cache_ttl_hours=ttl, shared_cache=shared_cache
                )
            return backend.search_similar_query(
                query_embedding, identity, threshold,
                gateway_id=gateway_id,
                cache_ttl_hours=ttl, shared_cache=shared_cache
            )
        return await self._with_reconnect(_op, runtime_settings)

    async def save_query_cache(
        self,
        query_text: str,
        query_embedding: List[float],
        sql_query: str,
        identity: str,
        gateway_id: str,
        runtime_settings=None,
        original_query_text: str = None,
        genie_space_id: str = None,
    ) -> int:
        """Save a new query to the cache."""
        async def _op():
            backend = await self._resolve_backend(runtime_settings)
            if hasattr(backend, 'pool'):
                return await backend.save_query_cache(
                    query_text, query_embedding, sql_query, identity, gateway_id,
                    original_query_text=original_query_text,
                    genie_space_id=genie_space_id,
                )
            return backend.save_query_cache(
                query_text, query_embedding, sql_query, identity, gateway_id,
                original_query_text=original_query_text,
                genie_space_id=genie_space_id,
            )
        return await self._with_reconnect(_op, runtime_settings)

    async def get_all_cached_queries(
        self,
        identity: Optional[str] = None,
        runtime_settings=None,
        gateway_id: Optional[str] = None,
    ) -> List[dict]:
        """Get all cached queries, optionally filtered by gateway_id."""
        async def _op():
            backend = await self._resolve_backend(runtime_settings)
            if hasattr(backend, 'pool'):
                return await backend.get_all_cached_queries(identity, gateway_id=gateway_id)
            return backend.get_all_cached_queries(identity, genie_space_id=gateway_id)
        return await self._with_reconnect(_op, runtime_settings)

    async def save_query_log(
        self,
        query_id: str,
        query_text: str,
        identity: str,
        stage: str,
        from_cache: bool = False,
        gateway_id: Optional[str] = None,
        runtime_settings=None
    ) -> Optional[int]:
        """Save a query log entry."""
        async def _op():
            backend = await self._resolve_backend(runtime_settings)
            if hasattr(backend, 'pool'):
                return await backend.save_query_log(
                    query_id, query_text, identity, stage, from_cache, gateway_id
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
        runtime_settings=None,
        gateway_id: Optional[str] = None,
    ) -> List[dict]:
        """Get query logs, optionally filtered by identity and/or gateway_id."""
        async def _op():
            backend = await self._resolve_backend(runtime_settings)
            if hasattr(backend, 'pool'):
                return await backend.get_query_logs(identity, limit, gateway_id=gateway_id)
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

    async def clear_cache(self, runtime_settings=None, gateway_id=None) -> int:
        """Delete cached queries, optionally filtered by genie_space_id."""
        async def _op():
            backend = await self._resolve_backend(runtime_settings)
            if hasattr(backend, 'clear_cache'):
                return await backend.clear_cache(gateway_id=gateway_id)
            return 0
        return await self._with_reconnect(_op, runtime_settings)

    # --- Gateway CRUD (delegates to default backend) ---

    async def create_gateway(self, config: dict) -> dict:
        """Create a new gateway configuration."""
        await self._ensure_backend_healthy(self.default_backend)
        backend = self.default_backend
        if hasattr(backend, 'pool'):
            return await backend.create_gateway(config)
        return backend.create_gateway(config)

    async def get_gateway(self, gateway_id: str):
        """Get a gateway configuration by ID."""
        await self._ensure_backend_healthy(self.default_backend)
        backend = self.default_backend
        if hasattr(backend, 'pool'):
            return await backend.get_gateway(gateway_id)
        return backend.get_gateway(gateway_id)

    async def list_gateways(self) -> list:
        """List all gateway configurations."""
        await self._ensure_backend_healthy(self.default_backend)
        backend = self.default_backend
        if hasattr(backend, 'pool'):
            return await backend.list_gateways()
        return backend.list_gateways()

    async def update_gateway(self, gateway_id: str, updates: dict):
        """Update a gateway configuration."""
        backend = self.default_backend
        if hasattr(backend, 'pool'):
            return await backend.update_gateway(gateway_id, updates)
        return backend.update_gateway(gateway_id, updates)

    async def delete_gateway(self, gateway_id: str) -> bool:
        """Delete a gateway configuration."""
        backend = self.default_backend
        if hasattr(backend, 'pool'):
            return await backend.delete_gateway(gateway_id)
        return backend.delete_gateway(gateway_id)

    async def get_gateway_stats(self, gateway_id: str) -> dict:
        """Get cache and query stats for a gateway."""
        backend = self.default_backend
        if hasattr(backend, 'pool'):
            return await backend.get_gateway_stats(gateway_id)
        return backend.get_gateway_stats(gateway_id)

    # --- User roles CRUD (delegates to default backend) ---

    async def get_user_role(self, identity: str):
        backend = self.default_backend
        if hasattr(backend, 'pool'):
            return await backend.get_user_role(identity)
        return backend.get_user_role(identity)

    async def set_user_role(self, identity: str, role: str, granted_by: str = None):
        backend = self.default_backend
        if hasattr(backend, 'pool'):
            return await backend.set_user_role(identity, role, granted_by)
        return backend.set_user_role(identity, role, granted_by)

    async def list_user_roles(self) -> list:
        backend = self.default_backend
        if hasattr(backend, 'pool'):
            return await backend.list_user_roles()
        return backend.list_user_roles()

    async def delete_user_role(self, identity: str):
        backend = self.default_backend
        if hasattr(backend, 'pool'):
            return await backend.delete_user_role(identity)
        return backend.delete_user_role(identity)

    async def count_owners(self) -> int:
        backend = self.default_backend
        if hasattr(backend, 'pool'):
            return await backend.count_owners()
        return backend.count_owners()
