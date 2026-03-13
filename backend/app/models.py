from pydantic import BaseModel
from typing import Optional, List, Any, Union
from datetime import datetime
from enum import Enum


class QueryStage(str, Enum):
    RECEIVED = "received"
    CHECKING_CACHE = "checking_cache"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    QUEUED = "queued"
    PROCESSING_GENIE = "processing_genie"
    EXECUTING_SQL = "executing_sql"
    COMPLETED = "completed"
    FAILED = "failed"


class RuntimeConfig(BaseModel):
    """Runtime configuration provided by frontend."""
    auth_mode: Optional[str] = "app"  # "app" or "user"
    user_pat: Optional[str] = None  # Optional: User's Personal Access Token for full API access
    genie_space_id: Optional[str] = None
    sql_warehouse_id: Optional[str] = None
    similarity_threshold: Optional[float] = None
    max_queries_per_minute: Optional[int] = None
    embedding_provider: Optional[str] = None
    databricks_embedding_endpoint: Optional[str] = None
    
    # Storage backend selection
    storage_backend: Optional[str] = None  # 'local' or 'lakebase'
    cache_ttl_hours: Optional[float] = None  # 0 = no freshness limit
    
    # Lakebase/PostgreSQL configuration (for PGVector caching)
    lakebase_instance_name: Optional[str] = None  # Lakebase instance name (e.g., my-lakebase-instance)
    lakebase_catalog: Optional[str] = None   # e.g., sean_lakebase_genie
    lakebase_schema: Optional[str] = None    # Usually 'public'
    cache_table_name: Optional[str] = None   # e.g., cached_queries
    query_log_table_name: Optional[str] = None  # e.g., query_logs

    # Cache scope
    shared_cache: Optional[bool] = True  # True = global cache, False = per-user cache

class QueryRequest(BaseModel):
    query: str
    identity: str
    config: Optional[RuntimeConfig] = None
    # Multi-turn conversation support
    conversation_id: Optional[str] = None           # Genie conversation_id from previous turn
    conversation_synced: Optional[bool] = None       # Whether Genie has seen all prior messages
    conversation_history: Optional[List[str]] = None  # Prior query texts in this tab


class QueryResponse(BaseModel):
    query_id: str
    stage: QueryStage
    message: str


class QueryStatus(BaseModel):
    query_id: str
    query_text: str
    identity: str
    stage: QueryStage
    created_at: datetime
    updated_at: datetime
    result: Optional[Union[dict, List[dict], Any]] = None  # Can be dict or list (Genie attachments)
    sql_query: Optional[str] = None
    error: Optional[str] = None
    from_cache: bool = False
    conversation_id: Optional[str] = None  # Genie conversation_id for multi-turn


class CachedQuery(BaseModel):
    id: int
    query_text: str
    sql_query: str
    identity: str
    genie_space_id: str
    created_at: datetime
    last_used: datetime
    use_count: int
    similarity: Optional[float] = None


class QueuedQuery(BaseModel):
    query_id: str
    query_text: str
    identity: str
    queued_at: datetime
    position: int


class QueryLog(BaseModel):
    """Query log entry"""
    query_id: str
    query_text: str
    identity: str
    stage: str
    created_at: datetime
    from_cache: bool = False
    genie_space_id: Optional[str] = None


class GenieAPIResponse(BaseModel):
    conversation_id: str
    message_id: str
    status: str
    result: Optional[Union[dict, List[dict], Any]] = None  # Can be dict or list (attachments)
    sql_query: Optional[str] = None
    attachments: Optional[List[dict]] = None  # Genie API attachments array


# --- Proxy API models (for /api/v1/ external consumers) ---

class ProxyQueryRequest(BaseModel):
    """External API request to submit a query."""
    query: str
    space_id: Optional[str] = None       # Falls back to server default
    warehouse_id: Optional[str] = None   # Falls back to server default
    identity: Optional[str] = None       # For cache isolation; defaults to "api-user"
    conversation_id: Optional[str] = None  # For multi-turn follow-ups


class ProxyQueryResponse(BaseModel):
    """External API response after submitting a query."""
    query_id: str
    status: str


class ProxyQueryStatusResponse(BaseModel):
    """External API response when polling query status."""
    query_id: str
    status: str
    stage: Optional[str] = None
    sql_query: Optional[str] = None
    result: Optional[Union[dict, List[dict], Any]] = None
    from_cache: bool = False
    error: Optional[str] = None
    conversation_id: Optional[str] = None
