"""
Runtime configuration management.
Allows frontend to override environment variables with user-provided config.
"""

import logging
from typing import Optional
from urllib.parse import quote_plus
from app.config import get_settings
from app.models import RuntimeConfig
from app.auth import get_service_principal_token

logger = logging.getLogger(__name__)
_base_settings = get_settings()


class RuntimeSettings:
    """Settings that can be overridden at runtime from frontend config."""

    def __init__(self, runtime_config: Optional[RuntimeConfig] = None, user_token: Optional[str] = None, user_email: Optional[str] = None):
        self.base = _base_settings
        self.runtime = runtime_config
        self.user_token = user_token
        self.user_email = user_email

        if self.runtime and self.runtime.lakebase_instance_name and self.runtime.user_pat:
            logger.info("Runtime Lakebase config: instance=%s, table=%s",
                        self.runtime.lakebase_instance_name, self.full_table_name)

    @property
    def postgres_connection_string(self) -> str:
        if self.runtime and self.runtime.lakebase_instance_name:
            db_user = self.user_email if self.user_email else self.base.postgres_user
            user = quote_plus(db_user)
            if not self.runtime.user_pat:
                raise ValueError("Lakebase requires a Databricks Personal Access Token (PAT).")
            password = quote_plus(self.runtime.user_pat)
            host = self.runtime.lakebase_instance_name
            port = self.base.postgres_port
            database = "databricks_postgres"
            return f"postgresql://{user}:{password}@{host}:{port}/{database}"
        return self.base.postgres_connection_string

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
        return table

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
        return table

    @property
    def auth_mode(self) -> str:
        return self.runtime.auth_mode if self.runtime and self.runtime.auth_mode else "app"

    @property
    def databricks_host(self) -> str:
        host = self.base.databricks_host
        return host.rstrip('/') if host else ""

    @property
    def databricks_token(self) -> str:
        if self.auth_mode == "user":
            if self.runtime and self.runtime.user_pat and self.runtime.user_pat.strip():
                return self.runtime.user_pat.strip()
            else:
                logger.error("User Auth mode requires a Personal Access Token")
                return ""

        sp_token = get_service_principal_token()
        if sp_token:
            return sp_token

        logger.warning("Falling back to DATABRICKS_TOKEN env var")
        return self.base.databricks_token

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
    def catalog_name(self) -> str:
        return self.base.catalog_name

    @property
    def schema_name(self) -> str:
        return self.base.schema_name

    @property
    def cache_table_name_setting(self) -> str:
        return self.base.cache_table_name

    @property
    def local_embedding_model(self) -> str:
        return self.base.local_embedding_model

    @property
    def shared_cache(self) -> bool:
        if self.runtime and self.runtime.shared_cache is not None:
            return self.runtime.shared_cache
        return True
