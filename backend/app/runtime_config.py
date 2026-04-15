"""
Runtime configuration management.
Allows frontend to override environment variables with user-provided config.
"""

import logging
from typing import Optional
from app.config import get_settings
from app.models import RuntimeConfig

logger = logging.getLogger(__name__)
_base_settings = get_settings()


class RuntimeSettings:
    """Settings that can be overridden at runtime from frontend config."""

    def __init__(self, runtime_config: Optional[RuntimeConfig] = None, user_token: Optional[str] = None, user_email: Optional[str] = None):
        self.base = _base_settings
        self.runtime = runtime_config
        self.user_token = user_token  # X-Forwarded-Access-Token (Genie/SQL/Workspace)
        self.user_email = user_email

    @property
    def databricks_host(self) -> str:
        host = self.base.databricks_host
        return host.rstrip('/') if host else ""

    @property
    def databricks_token(self) -> str:
        """Token for Genie/SQL Warehouse/Workspace API calls.
        Always X-Forwarded-Access-Token (user's OAuth token injected by Databricks Apps).
        Lakebase uses DATABRICKS_TOKEN env var separately — never this property.
        """
        if not self.user_token or not self.user_token.strip():
            logger.error("No X-Forwarded-Access-Token available — request outside Databricks Apps context?")
            return ""
        return self.user_token.strip()

    @property
    def gateway_id(self) -> str:
        return self.runtime.gateway_id if self.runtime and self.runtime.gateway_id else None

    @property
    def cache_namespace(self) -> str:
        return self.gateway_id or self.genie_space_id

    @property
    def caching_enabled(self) -> bool:
        if self.runtime and hasattr(self.runtime, 'caching_enabled') and self.runtime.caching_enabled is not None:
            return self.runtime.caching_enabled
        return True

    @property
    def genie_space_id(self) -> str:
        return (self.runtime.genie_space_id if self.runtime and self.runtime.genie_space_id and self.runtime.genie_space_id.strip()
                else self.base.genie_space_id)

    @property
    def sql_warehouse_id(self) -> str:
        return (self.runtime.sql_warehouse_id if self.runtime and self.runtime.sql_warehouse_id and self.runtime.sql_warehouse_id.strip()
                else self.base.sql_warehouse_id)

    @property
    def similarity_threshold(self) -> float:
        return (self.runtime.similarity_threshold if self.runtime and self.runtime.similarity_threshold
                else self.base.similarity_threshold)

    @property
    def max_queries_per_minute(self) -> int:
        return (self.runtime.max_queries_per_minute if self.runtime and self.runtime.max_queries_per_minute
                else self.base.max_queries_per_minute)

    @property
    def cache_ttl_hours(self) -> float:
        return (self.runtime.cache_ttl_hours if self.runtime and self.runtime.cache_ttl_hours is not None
                else self.base.cache_ttl_hours)

    @property
    def embedding_provider(self) -> str:
        return (self.runtime.embedding_provider if self.runtime and self.runtime.embedding_provider
                else self.base.embedding_provider)

    @property
    def databricks_embedding_endpoint(self) -> str:
        return (self.runtime.databricks_embedding_endpoint if self.runtime and self.runtime.databricks_embedding_endpoint
                else self.base.databricks_embedding_endpoint)

    @property
    def app_env(self) -> str:
        return self.base.app_env

    @property
    def storage_backend(self) -> str:
        if self.runtime and self.runtime.storage_backend == 'lakebase':
            return 'pgvector'
        if self.runtime and self.runtime.storage_backend:
            return self.runtime.storage_backend
        return self.base.storage_backend

    @property
    def is_databricks(self) -> bool:
        return self.base.is_databricks

    @property
    def local_cache_file(self) -> str:
        return self.base.local_cache_file

    @property
    def local_embeddings_file(self) -> str:
        return self.base.local_embeddings_file

    @property
    def shared_cache(self) -> bool:
        if self.runtime and self.runtime.shared_cache is not None:
            return self.runtime.shared_cache
        return self.base.shared_cache

    @property
    def question_normalization_enabled(self) -> bool:
        from app.api.config_store import get_effective_setting
        if self.runtime and self.runtime.question_normalization_enabled is not None:
            return self.runtime.question_normalization_enabled
        val = get_effective_setting("question_normalization_enabled")
        return val if val is not None else True

    @property
    def cache_validation_enabled(self) -> bool:
        from app.api.config_store import get_effective_setting
        if self.runtime and self.runtime.cache_validation_enabled is not None:
            return self.runtime.cache_validation_enabled
        val = get_effective_setting("cache_validation_enabled")
        return val if val is not None else True

    @property
    def full_table_name(self) -> str:
        catalog = (self.runtime.lakebase_catalog if self.runtime and self.runtime.lakebase_catalog
                  else self.base.lakebase_catalog)
        schema = (self.runtime.lakebase_schema if self.runtime and self.runtime.lakebase_schema
                 else self.base.lakebase_schema)
        table = (self.runtime.cache_table_name if self.runtime and self.runtime.cache_table_name
                else self.base.pgvector_table_name)
        if catalog:
            return f"{catalog}.{schema}.{table}"
        return f"{schema}.{table}"

    @property
    def query_log_table_name(self) -> str:
        catalog = (self.runtime.lakebase_catalog if self.runtime and self.runtime.lakebase_catalog
                  else self.base.lakebase_catalog)
        schema = (self.runtime.lakebase_schema if self.runtime and self.runtime.lakebase_schema
                 else self.base.lakebase_schema)
        table = (self.runtime.query_log_table_name if self.runtime and self.runtime.query_log_table_name
                else "query_logs")
        if catalog:
            return f"{catalog}.{schema}.{table}"
        return f"{schema}.{table}"

    @property
    def postgres_connection_string(self) -> str:
        return self.base.postgres_connection_string
