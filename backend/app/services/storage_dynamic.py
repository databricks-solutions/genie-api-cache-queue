"""
Dynamic storage service that can switch backends at runtime.
Useful for Databricks Apps where Lakebase config comes from frontend.

Design note: PGVector operations are async (asyncpg) but this service is called
from sync queue processing code. The threading model (dedicated event loop per
backend, run_coroutine_threadsafe) works but adds complexity. A cleaner approach
would make query processing fully async end-to-end.
"""

import logging
from typing import Optional, List, Tuple
import asyncio
import threading
import time

logger = logging.getLogger(__name__)


class DynamicStorageService:
    """
    Storage service that dynamically selects backend based on runtime config.
    Falls back to default backend when no runtime config is provided.
    """

    _DEFAULT_KEY = "__default__"

    def __init__(self, default_backend, default_loop_info=None):
        self.default_backend = default_backend
        self._pgvector_backends = {}
        self._pgvector_loops = {}
        self._token_expiry = {}

        if default_loop_info and hasattr(default_backend, 'pool'):
            self._pgvector_backends[self._DEFAULT_KEY] = default_backend
            self._pgvector_loops[self._DEFAULT_KEY] = default_loop_info
            self._token_expiry[self._DEFAULT_KEY] = time.time() + 3300
            logger.info("Registered default PGVector backend with persistent event loop")

    def refresh_default_backend(self):
        """Proactively refresh the default PGVector backend's OAuth token.
        Called periodically by a background thread in database.py."""
        cache_key = self._DEFAULT_KEY
        if cache_key not in self._pgvector_backends:
            return

        if not self._is_token_expired(cache_key):
            return

        logger.info("Background refresh: regenerating OAuth token for default backend")
        try:
            from app.config import get_settings
            from app.services.storage_pgvector import PGVectorStorageService
            from databricks.sdk import WorkspaceClient
            from urllib.parse import quote_plus
            import uuid as _uuid

            settings = get_settings()

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
            new_conn_string = f"postgresql://{_user}:{_password}@{_host}:{_port}/databricks_postgres?sslmode={settings.postgres_sslmode}"

            # Tear down old backend
            old_loop_info = self._pgvector_loops.get(cache_key)
            if old_loop_info:
                old_loop_info['loop'].call_soon_threadsafe(old_loop_info['loop'].stop)

            # Create new backend with fresh token
            new_backend = PGVectorStorageService(
                connection_string=new_conn_string,
                table_name=settings.full_table_name,
                cache_ttl_hours=settings.cache_ttl_hours
            )

            loop_ready = threading.Event()
            loop_container = {}

            def run_event_loop():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop_container['loop'] = loop
                loop.run_until_complete(new_backend.initialize())
                loop_ready.set()
                loop.run_forever()

            thread = threading.Thread(target=run_event_loop, daemon=True)
            thread.start()
            loop_ready.wait(timeout=30)

            loop = loop_container['loop']

            self._pgvector_backends[cache_key] = new_backend
            self._pgvector_loops[cache_key] = {'loop': loop, 'thread': thread}
            self._token_expiry[cache_key] = time.time() + 3300
            self.default_backend = new_backend

            logger.info("Background refresh: OAuth token refreshed successfully (next in 55min)")
        except Exception:
            logger.exception("Background refresh: failed to refresh OAuth token")

    def _get_backend(self, runtime_settings=None):
        """Get the appropriate backend based on runtime settings"""
        if not runtime_settings:
            return self.default_backend

        if hasattr(runtime_settings, 'runtime') and runtime_settings.runtime:
            if (runtime_settings.runtime.storage_backend == 'lakebase' and
                runtime_settings.runtime.lakebase_instance_name and
                runtime_settings.runtime.user_pat):
                if self._DEFAULT_KEY in self._pgvector_backends:
                    return self._pgvector_backends[self._DEFAULT_KEY]
                return self._get_or_create_pgvector_backend(runtime_settings)

            if runtime_settings.runtime.storage_backend == 'local':
                return self.default_backend

        return self.default_backend

    def _get_cache_key(self, runtime_settings):
        """Generate cache key for the backend's persistent event loop."""
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
        """Check if OAuth token is expired or will expire soon (within 5 minutes)"""
        if cache_key not in self._token_expiry:
            return True
        return (self._token_expiry[cache_key] - time.time()) < 300

    def _refresh_backend_if_needed(self, cache_key, runtime_settings):
        """Refresh backend if OAuth token is expired"""
        if self._is_token_expired(cache_key):
            logger.info("OAuth token expired or expiring soon, refreshing Lakebase connection")
            if cache_key in self._pgvector_backends:
                del self._pgvector_backends[cache_key]
            if cache_key in self._pgvector_loops:
                old_loop_info = self._pgvector_loops[cache_key]
                old_loop_info['loop'].call_soon_threadsafe(old_loop_info['loop'].stop)
                del self._pgvector_loops[cache_key]
            if cache_key in self._token_expiry:
                del self._token_expiry[cache_key]
            return True
        return False

    def _get_or_create_pgvector_backend(self, runtime_settings):
        """Get or create a PGVector backend with persistent event loop"""
        cache_key = self._get_cache_key(runtime_settings)

        self._refresh_backend_if_needed(cache_key, runtime_settings)

        if cache_key not in self._pgvector_backends:
            logger.info("Creating Lakebase connection: instance=%s table=%s",
                         runtime_settings.runtime.lakebase_instance_name,
                         runtime_settings.full_table_name)

            try:
                from app.services.storage_pgvector import PGVectorStorageService

                # Pass cache_ttl_hours from runtime settings
                ttl = runtime_settings.cache_ttl_hours if hasattr(runtime_settings, 'cache_ttl_hours') else 24

                backend = PGVectorStorageService(
                    connection_string=runtime_settings.postgres_connection_string,
                    table_name=runtime_settings.full_table_name,
                    query_log_table_name=runtime_settings.query_log_table_name,
                    databricks_pat=runtime_settings.runtime.user_pat if runtime_settings.runtime else None,
                    databricks_host=runtime_settings.databricks_host,
                    lakebase_instance_name=runtime_settings.runtime.lakebase_instance_name if runtime_settings.runtime else None,
                    cache_ttl_hours=ttl
                )

                loop_ready = threading.Event()
                loop_container = {}

                def run_event_loop():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop_container['loop'] = loop
                    loop_ready.set()
                    loop.run_forever()

                thread = threading.Thread(target=run_event_loop, daemon=True)
                thread.start()
                loop_ready.wait()

                loop = loop_container['loop']

                future = asyncio.run_coroutine_threadsafe(backend.initialize(), loop)
                future.result(timeout=30)

                self._token_expiry[cache_key] = time.time() + 3300

                logger.info("Lakebase connection initialized (token refresh in 55min)")

                self._pgvector_backends[cache_key] = backend
                self._pgvector_loops[cache_key] = {
                    'loop': loop,
                    'thread': thread
                }
            except Exception:
                logger.exception("Failed to initialize Lakebase")
                raise

        return self._pgvector_backends[cache_key]

    def _run_in_loop(self, backend, coro, runtime_settings, timeout=30):
        """Helper: run async coroutine in the backend's persistent event loop."""
        cache_key = self._get_cache_key(runtime_settings)
        loop_info = self._pgvector_loops.get(cache_key)

        if not loop_info:
            raise RuntimeError("PGVector backend not properly initialized")

        future = asyncio.run_coroutine_threadsafe(coro, loop_info['loop'])
        return future.result(timeout=timeout)

    def search_similar_query(
        self,
        query_embedding: List[float],
        identity: str,
        threshold: float,
        genie_space_id: Optional[str] = None,
        runtime_settings=None,
        shared_cache: bool = True
    ) -> Optional[Tuple[int, str, str, float]]:
        """Search for similar cached queries using vector similarity."""
        backend = self._get_backend(runtime_settings)

        if hasattr(backend, 'pool'):
            try:
                ttl = runtime_settings.cache_ttl_hours if runtime_settings and hasattr(runtime_settings, 'cache_ttl_hours') else None

                coro = backend.search_similar_query(
                    query_embedding, identity, threshold, genie_space_id,
                    cache_ttl_hours=ttl, shared_cache=shared_cache
                )
                return self._run_in_loop(backend, coro, runtime_settings)
            except Exception:
                logger.exception("PGVector search failed")
                raise

        # Local storage
        ttl = runtime_settings.cache_ttl_hours if runtime_settings and hasattr(runtime_settings, 'cache_ttl_hours') else None
        return backend.search_similar_query(
            query_embedding, identity, threshold,
            cache_ttl_hours=ttl, shared_cache=shared_cache
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
        backend = self._get_backend(runtime_settings)

        if hasattr(backend, 'pool'):
            try:
                coro = backend.save_query_cache(
                    query_text, query_embedding, sql_query, identity, genie_space_id
                )
                return self._run_in_loop(backend, coro, runtime_settings)
            except Exception:
                logger.exception("PGVector save failed")
                raise

        return backend.save_query_cache(
            query_text, query_embedding, sql_query, identity, genie_space_id
        )

    def get_all_cached_queries(
        self,
        identity: Optional[str] = None,
        runtime_settings=None
    ) -> List[dict]:
        """Get all cached queries (full history, no TTL filtering)."""
        backend = self._get_backend(runtime_settings)

        if hasattr(backend, 'pool'):
            try:
                coro = backend.get_all_cached_queries(identity)
                return self._run_in_loop(backend, coro, runtime_settings)
            except Exception:
                logger.exception("PGVector get_all failed")
                raise

        return backend.get_all_cached_queries(identity)

    def save_query_log(
        self,
        query_id: str,
        query_text: str,
        identity: str,
        stage: str,
        from_cache: bool = False,
        genie_space_id: Optional[str] = None,
        runtime_settings=None
    ) -> Optional[int]:
        """Save a query log entry"""
        backend = self._get_backend(runtime_settings)

        if hasattr(backend, 'pool'):
            try:
                cache_key = self._get_cache_key(runtime_settings)
                loop_info = self._pgvector_loops.get(cache_key)

                if not loop_info:
                    logger.warning("Backend not initialized, skipping log save")
                    return None

                coro = backend.save_query_log(
                    query_id, query_text, identity, stage, from_cache, genie_space_id
                )
                future = asyncio.run_coroutine_threadsafe(coro, loop_info['loop'])
                return future.result(timeout=10)
            except Exception as e:
                logger.warning("PGVector save_query_log failed: %s", e)
                return None

        return None

    def get_query_logs(
        self,
        identity: Optional[str] = None,
        limit: int = 50,
        runtime_settings=None
    ) -> List[dict]:
        """Get query logs"""
        backend = self._get_backend(runtime_settings)

        if hasattr(backend, 'pool'):
            try:
                cache_key = self._get_cache_key(runtime_settings)
                loop_info = self._pgvector_loops.get(cache_key)

                if not loop_info:
                    return []

                coro = backend.get_query_logs(identity, limit)
                future = asyncio.run_coroutine_threadsafe(coro, loop_info['loop'])
                return future.result(timeout=30)
            except Exception as e:
                logger.warning("PGVector get_query_logs failed: %s", e)
                return []

        return []
