"""
Database abstraction layer that supports local and PGVector (Lakebase) storage.
Automatically selects the appropriate backend based on environment.
Supports dynamic backend switching for Databricks Apps.

Design note: OAuth token generation, thread creation, and pool initialization
happen at import time (module level). In production, these should be moved into
FastAPI's lifespan context manager to enable clean startup/shutdown.
"""

import logging
from typing import Optional, List, Tuple
from app.config import get_settings
import asyncio
import threading

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize default backend based on environment configuration
if settings.storage_backend == "pgvector":
    from app.services.storage_pgvector import PGVectorStorageService

    _conn_string = settings.postgres_connection_string

    if settings.lakebase_instance and settings.databricks_token and settings.databricks_host:
        try:
            from databricks.sdk import WorkspaceClient
            from urllib.parse import quote_plus
            import uuid as _uuid

            logger.info("Generating OAuth token for Lakebase Autoscaling...")
            _client = WorkspaceClient(
                host=settings.databricks_host,
                token=settings.databricks_token,
                auth_type="pat"
            )
            _instance_name = next(
                (i.name for i in _client.database.list_database_instances()
                 if i.state and i.state.value == "AVAILABLE"),
                None
            )
            _cred_kwargs = {"request_id": str(_uuid.uuid4())}
            if _instance_name:
                _cred_kwargs["instance_names"] = [_instance_name]
            _cred = _client.database.generate_database_credential(**_cred_kwargs)
            _oauth_token = _cred.token
            _user = quote_plus(settings.postgres_user)
            _password = quote_plus(_oauth_token)
            _host = settings.lakebase_instance
            _port = settings.postgres_port
            _conn_string = f"postgresql://{_user}:{_password}@{_host}:{_port}/databricks_postgres?sslmode={settings.postgres_sslmode}"
            logger.info("OAuth token generated (expires in %ds)", getattr(_cred, 'expires_in', 3600))
        except Exception as e:
            logger.warning("OAuth token generation failed: %s, using connection string as-is", e)

    _default_backend = PGVectorStorageService(
        connection_string=_conn_string,
        table_name=settings.full_table_name,
        cache_ttl_hours=settings.cache_ttl_hours
    )

    _default_loop_ready = threading.Event()
    _default_loop_container = {}

    def _run_default_loop():
        import asyncio as _aio
        _aio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
        loop = _aio.new_event_loop()
        _aio.set_event_loop(loop)
        _default_loop_container['loop'] = loop
        loop.run_until_complete(_default_backend.initialize())
        _default_loop_ready.set()
        loop.run_forever()

    _init_thread = threading.Thread(target=_run_default_loop, daemon=True)
    _init_thread.start()
    _default_loop_ready.wait()
    _default_pgvector_loop = _default_loop_container['loop']
    _default_pgvector_thread = _init_thread

    if settings.lakebase_instance:
        logger.info("Default storage: Databricks Lakebase (PGVector): %s table=%s",
                     settings.lakebase_instance, settings.full_table_name)
    else:
        logger.info("Default storage: PGVector: %s:%d/%s table=%s",
                     settings.postgres_host, settings.postgres_port,
                     settings.postgres_database, settings.full_table_name)
else:
    from app.services.storage_local import get_local_storage
    _default_backend = get_local_storage(
        settings.local_cache_file,
        settings.local_embeddings_file,
        settings.cache_ttl_hours
    )
    logger.info("Default storage: Local file-based (configure Lakebase in Settings for cloud storage)")

# Use dynamic storage service for runtime backend switching
from app.services.storage_dynamic import DynamicStorageService
_default_loop_info = None
if settings.storage_backend == "pgvector":
    _default_loop_info = {'loop': _default_pgvector_loop, 'thread': _default_pgvector_thread}
_storage_backend = DynamicStorageService(_default_backend, _default_loop_info)

# Background thread to refresh OAuth token for default PGVector/Lakebase backend
if settings.storage_backend == "pgvector" and settings.lakebase_instance:
    import time as _time

    def _token_refresh_loop():
        while True:
            _time.sleep(45 * 60)  # Every 45 minutes
            try:
                logger.info("Background token refresh: checking default backend")
                _storage_backend.refresh_default_backend()
            except Exception as _e:
                logger.error("Background token refresh failed: %s", _e)

    _refresh_thread = threading.Thread(target=_token_refresh_loop, daemon=True, name="token-refresh")
    _refresh_thread.start()
    logger.info("Started background OAuth token refresh thread (every 45 min)")


class DatabaseService:
    """
    Unified database service that works in both local and Databricks environments.
    """

    def __init__(self):
        self.backend = _storage_backend

    def search_similar_query(
        self,
        query_embedding: List[float],
        identity: str,
        threshold: float = None,
        genie_space_id: Optional[str] = None,
        runtime_settings=None,
        shared_cache: bool = True
    ) -> Optional[Tuple[int, str, str, float]]:
        """Search for similar cached queries using vector similarity."""
        if threshold is None:
            threshold = settings.similarity_threshold

        return self.backend.search_similar_query(
            query_embedding,
            identity,
            threshold,
            genie_space_id,
            runtime_settings,
            shared_cache=shared_cache
        )

    def save_query_cache(
        self,
        query_text: str,
        query_embedding: List[float],
        sql_query: str,
        identity: str,
        genie_space_id: str,
        runtime_settings=None
    ) -> int:
        """Save a new query to the cache."""
        return self.backend.save_query_cache(
            query_text, query_embedding, sql_query, identity, genie_space_id, runtime_settings
        )

    def get_all_cached_queries(self, identity: Optional[str] = None, runtime_settings=None) -> List[dict]:
        """Get all cached queries (full history)."""
        return self.backend.get_all_cached_queries(identity, runtime_settings)

    def save_query_log(self, query_id, query_text, identity, stage, from_cache=False, genie_space_id=None, runtime_settings=None):
        """Save a query log entry"""
        return self.backend.save_query_log(query_id, query_text, identity, stage, from_cache, genie_space_id, runtime_settings)

    def get_query_logs(self, identity=None, limit=50, runtime_settings=None):
        """Get query logs"""
        return self.backend.get_query_logs(identity, limit, runtime_settings)


db_service = DatabaseService()
