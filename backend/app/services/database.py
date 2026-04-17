"""
Database abstraction layer for Lakebase (PGVector) storage.
Initialization happens in FastAPI lifespan via initialize_storage().
"""

import logging
from typing import Optional, List, Tuple
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Set during lifespan initialization
_storage_backend = None
db_service = None


async def initialize_storage():
    """
    Initialize storage backend. Called from FastAPI lifespan.
    Returns the DynamicStorageService instance for token refresh scheduling.
    """
    global _storage_backend, db_service

    from app.services.storage_dynamic import DynamicStorageService
    from app.services.storage_pgvector import PGVectorStorageService

    # Token resolution order:
    # 1) lakebase_service_token from Settings UI (config_store override)
    # 2) Service principal OAuth token (Databricks Apps auto-injects
    #    DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET)
    from app.api.config_store import get_effective_setting
    from app.auth import get_service_principal_token

    token = get_effective_setting("lakebase_service_token")
    if token:
        src = "Settings override"
    else:
        token = get_service_principal_token()
        src = "Service principal OAuth"
    if not token:
        raise RuntimeError(
            "No token available for Lakebase. Ensure the app's service principal "
            "credentials (DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET) are "
            "configured, or set Lakebase Service Token in Settings."
        )
    logger.info("Lakebase token source: %s", src)

    default_backend = PGVectorStorageService(
        connection_string=settings.postgres_connection_string,
        table_name=settings.full_table_name,
        cache_ttl_hours=settings.cache_ttl_hours,
        lakebase_service_token=token,
        databricks_host=settings.databricks_host,
        lakebase_instance_name=settings.lakebase_instance,
    )
    await default_backend.initialize()

    if settings.lakebase_instance:
        logger.info("Default storage: Lakebase (PGVector): %s table=%s",
                    settings.lakebase_instance, settings.full_table_name)
    else:
        logger.info("Default storage: PGVector: %s:%d/%s table=%s",
                    settings.postgres_host, settings.postgres_port,
                    settings.postgres_database, settings.full_table_name)

    _storage_backend = DynamicStorageService(default_backend)

    if settings.lakebase_instance:
        _storage_backend._pgvector_backends[DynamicStorageService._DEFAULT_KEY] = default_backend

    db_service = DatabaseService()
    return _storage_backend


class DatabaseService:
    """Unified database service. All methods are async."""

    @property
    def backend(self):
        return _storage_backend

    async def search_similar_query(
        self,
        query_embedding: List[float],
        identity: str,
        threshold: float = None,
        gateway_id: Optional[str] = None,
        runtime_settings=None,
        shared_cache: bool = True
    ) -> Optional[Tuple[int, str, str, float]]:
        if threshold is None:
            threshold = settings.similarity_threshold
        return await self.backend.search_similar_query(
            query_embedding, identity, threshold, gateway_id, runtime_settings, shared_cache=shared_cache
        )

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
        return await self.backend.save_query_cache(
            query_text, query_embedding, sql_query, identity, gateway_id, runtime_settings,
            original_query_text=original_query_text,
            genie_space_id=genie_space_id,
        )

    async def get_all_cached_queries(self, identity: Optional[str] = None, runtime_settings=None, gateway_id: Optional[str] = None) -> List[dict]:
        return await self.backend.get_all_cached_queries(identity, runtime_settings, gateway_id=gateway_id)

    async def save_query_log(self, query_id, query_text, identity, stage, from_cache=False, gateway_id=None, runtime_settings=None):
        return await self.backend.save_query_log(query_id, query_text, identity, stage, from_cache, gateway_id, runtime_settings)

    async def get_query_logs(self, identity=None, limit=50, runtime_settings=None, gateway_id=None):
        return await self.backend.get_query_logs(identity, limit, runtime_settings, gateway_id=gateway_id)

    async def get_cache_count(self, runtime_settings=None):
        return await self.backend.get_cache_count(runtime_settings)

    async def clear_cache(self, runtime_settings=None, gateway_id=None) -> int:
        return await self.backend.clear_cache(runtime_settings, gateway_id=gateway_id)

    async def delete_cache_entries(self, entry_ids, gateway_id, runtime_settings=None) -> int:
        return await self.backend.delete_cache_entries(entry_ids, gateway_id, runtime_settings=runtime_settings)

    # --- Gateway CRUD ---

    async def create_gateway(self, config: dict) -> dict:
        return await self.backend.create_gateway(config)

    async def get_gateway(self, gateway_id: str):
        return await self.backend.get_gateway(gateway_id)

    async def list_gateways(self) -> list:
        return await self.backend.list_gateways()

    async def update_gateway(self, gateway_id: str, updates: dict):
        return await self.backend.update_gateway(gateway_id, updates)

    async def delete_gateway(self, gateway_id: str) -> bool:
        return await self.backend.delete_gateway(gateway_id)

    async def get_gateway_stats(self, gateway_id: str) -> dict:
        return await self.backend.get_gateway_stats(gateway_id)

    # --- User roles ---

    async def get_user_role(self, identity: str):
        return await self.backend.get_user_role(identity)

    async def set_user_role(self, identity: str, role: str, granted_by: str = None):
        return await self.backend.set_user_role(identity, role, granted_by)

    async def list_user_roles(self) -> list:
        return await self.backend.list_user_roles()

    async def delete_user_role(self, identity: str):
        return await self.backend.delete_user_role(identity)

    async def count_owners(self) -> int:
        return await self.backend.count_owners()

    # --- Group roles ---

    async def get_group_role(self, group_name: str):
        return await self.backend.get_group_role(group_name)

    async def set_group_role(self, group_name: str, role: str, granted_by: str = None):
        return await self.backend.set_group_role(group_name, role, granted_by)

    async def list_group_roles(self) -> list:
        return await self.backend.list_group_roles()

    async def delete_group_role(self, group_name: str):
        return await self.backend.delete_group_role(group_name)
