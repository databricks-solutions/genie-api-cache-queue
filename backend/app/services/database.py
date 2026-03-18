"""
Database abstraction layer that supports local and PGVector (Lakebase) storage.
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

    if settings.storage_backend == "pgvector":
        from app.services.storage_pgvector import PGVectorStorageService

        # Use PAT if available, otherwise SP token (Databricks Apps)
        token = settings.databricks_token
        if not token:
            from app.auth import get_service_principal_token
            token = get_service_principal_token()
            if token:
                logger.info("Using Service Principal token for Lakebase initialization")

        default_backend = PGVectorStorageService(
            connection_string=settings.postgres_connection_string,
            table_name=settings.full_table_name,
            cache_ttl_hours=settings.cache_ttl_hours,
            databricks_pat=token,
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
    else:
        from app.services.storage_local import get_local_storage
        default_backend = get_local_storage(
            settings.local_cache_file,
            settings.local_embeddings_file,
            settings.cache_ttl_hours
        )
        logger.info("Default storage: Local file-based (configure Lakebase in Settings for cloud storage)")

    _storage_backend = DynamicStorageService(default_backend)

    # Register default PGVector backend for reuse by per-user lakebase requests
    if settings.storage_backend == "pgvector" and settings.lakebase_instance:
        import time
        _storage_backend._pgvector_backends[DynamicStorageService._DEFAULT_KEY] = default_backend
        _storage_backend._token_expiry[DynamicStorageService._DEFAULT_KEY] = time.time() + 3300

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
        genie_space_id: Optional[str] = None,
        runtime_settings=None,
        shared_cache: bool = True
    ) -> Optional[Tuple[int, str, str, float]]:
        if threshold is None:
            threshold = settings.similarity_threshold
        return await self.backend.search_similar_query(
            query_embedding, identity, threshold, genie_space_id, runtime_settings, shared_cache=shared_cache
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
        return await self.backend.save_query_cache(
            query_text, query_embedding, sql_query, identity, genie_space_id, runtime_settings
        )

    async def get_all_cached_queries(self, identity: Optional[str] = None, runtime_settings=None) -> List[dict]:
        return await self.backend.get_all_cached_queries(identity, runtime_settings)

    async def save_query_log(self, query_id, query_text, identity, stage, from_cache=False, genie_space_id=None, runtime_settings=None):
        return await self.backend.save_query_log(query_id, query_text, identity, stage, from_cache, genie_space_id, runtime_settings)

    async def get_query_logs(self, identity=None, limit=50, runtime_settings=None):
        return await self.backend.get_query_logs(identity, limit, runtime_settings)

    async def clear_cache(self, runtime_settings=None) -> int:
        return await self.backend.clear_cache(runtime_settings)
