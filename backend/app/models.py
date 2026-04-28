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
    gateway_id: Optional[str] = None
    genie_space_id: Optional[str] = None
    genie_spaces: Optional[list] = None  # List of {"id": "...", "name": "..."}
    sql_warehouse_id: Optional[str] = None
    similarity_threshold: Optional[float] = None
    max_queries_per_minute: Optional[int] = None
    embedding_provider: Optional[str] = None
    databricks_embedding_endpoint: Optional[str] = None

    # Storage backend selection
    storage_backend: Optional[str] = None  # 'lakebase'
    cache_ttl_hours: Optional[float] = None  # 0 = no freshness limit

    # Lakebase/PostgreSQL configuration (for PGVector caching)
    lakebase_instance_name: Optional[str] = None  # Lakebase instance name (e.g., my-lakebase-instance)
    lakebase_catalog: Optional[str] = None   # e.g., sean_lakebase_genie
    lakebase_schema: Optional[str] = None    # Usually 'public'
    cache_table_name: Optional[str] = None   # e.g., cached_queries
    query_log_table_name: Optional[str] = None  # e.g., query_logs

    # Cache scope
    shared_cache: Optional[bool] = True  # True = global cache, False = per-user cache

    # Feature flags
    question_normalization_enabled: Optional[bool] = None  # LLM-based question normalization
    cache_validation_enabled: Optional[bool] = None  # LLM-based cache hit validation
    caching_enabled: Optional[bool] = None  # Enable/disable semantic cache entirely
    intent_split_enabled: Optional[bool] = None  # LLM-based intent split

    # LLM serving endpoints (per-service overrides; fall back to module default)
    normalization_model: Optional[str] = None
    validation_model: Optional[str] = None
    intent_split_model: Optional[str] = None

class QueryRequest(BaseModel):
    query: str
    config: Optional[RuntimeConfig] = None
    gateway_id: Optional[str] = None
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
    query_text: Optional[str] = None
    identity: Optional[str] = None
    stage: QueryStage
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
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
    gateway_id: str
    genie_space_id: Optional[str] = None  # audit/reference only
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
    gateway_id: Optional[str] = None


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


# --- Gateway CRUD models ---

class GatewayConfig(BaseModel):
    """Gateway configuration stored in database."""
    id: str
    name: str
    genie_space_id: str
    sql_warehouse_id: str
    similarity_threshold: float = 0.92
    max_queries_per_minute: int = 5
    cache_ttl_hours: float = 24
    question_normalization_enabled: bool = False
    cache_validation_enabled: bool = False
    caching_enabled: bool = True
    embedding_provider: str = "databricks"
    databricks_embedding_endpoint: str = "databricks-gte-large-en"
    shared_cache: bool = True
    status: str = "active"
    created_by: Optional[str] = None
    description: str = ""
    normalization_model: Optional[str] = None
    validation_model: Optional[str] = None
    intent_split_model: Optional[str] = None
    intent_split_enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Stats (populated on list/get, not stored)
    cache_entries: Optional[int] = None
    query_count_7d: Optional[int] = None


class GatewayCreateRequest(BaseModel):
    name: str
    genie_space_id: str
    sql_warehouse_id: Optional[str] = None
    similarity_threshold: Optional[float] = None
    max_queries_per_minute: Optional[int] = None
    cache_ttl_hours: Optional[float] = None
    question_normalization_enabled: Optional[bool] = None
    cache_validation_enabled: Optional[bool] = None
    caching_enabled: Optional[bool] = None
    embedding_provider: Optional[str] = None
    databricks_embedding_endpoint: Optional[str] = None
    shared_cache: Optional[bool] = None
    normalization_model: Optional[str] = None
    validation_model: Optional[str] = None
    intent_split_model: Optional[str] = None
    intent_split_enabled: Optional[bool] = None
    description: Optional[str] = ""


class GatewayUpdateRequest(BaseModel):
    name: Optional[str] = None
    similarity_threshold: Optional[float] = None
    max_queries_per_minute: Optional[int] = None
    cache_ttl_hours: Optional[float] = None
    question_normalization_enabled: Optional[bool] = None
    cache_validation_enabled: Optional[bool] = None
    caching_enabled: Optional[bool] = None
    embedding_provider: Optional[str] = None
    databricks_embedding_endpoint: Optional[str] = None
    shared_cache: Optional[bool] = None
    sql_warehouse_id: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None
    normalization_model: Optional[str] = None
    validation_model: Optional[str] = None
    intent_split_model: Optional[str] = None
    intent_split_enabled: Optional[bool] = None


# --- Router CRUD models ---

class RouterMember(BaseModel):
    """A (router, gateway) edge carrying the catalog metadata the selector sees.

    `when_to_use` is the critical routing hint and belongs on the edge (not the
    gateway) so one gateway can play different roles in different routers.
    """
    router_id: str
    gateway_id: str
    ordinal: int = 0
    title: str
    when_to_use: str
    tables: List[str] = []
    sample_questions: List[str] = []
    disabled: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RouterConfig(BaseModel):
    """Router configuration stored in the `routers` table."""
    id: str
    name: str
    description: str = ""
    status: str = "active"
    selector_model: Optional[str] = None
    selector_system_prompt: Optional[str] = None
    decompose_enabled: bool = True
    routing_cache_enabled: bool = True
    similarity_threshold: float = 0.92
    cache_ttl_hours: int = 24
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    members: Optional[List[RouterMember]] = None  # hydrated on GET /routers/{id}


class RouterMemberCreateRequest(BaseModel):
    gateway_id: str
    title: Optional[str] = None  # defaults to gateway.name server-side if omitted
    when_to_use: str
    ordinal: Optional[int] = None
    tables: Optional[List[str]] = None
    sample_questions: Optional[List[str]] = None
    disabled: Optional[bool] = None


class RouterMemberUpdateRequest(BaseModel):
    title: Optional[str] = None
    when_to_use: Optional[str] = None
    ordinal: Optional[int] = None
    tables: Optional[List[str]] = None
    sample_questions: Optional[List[str]] = None
    disabled: Optional[bool] = None


class RouterCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    selector_model: Optional[str] = None
    selector_system_prompt: Optional[str] = None
    decompose_enabled: Optional[bool] = None
    routing_cache_enabled: Optional[bool] = None
    similarity_threshold: Optional[float] = None
    cache_ttl_hours: Optional[int] = None
    members: Optional[List[RouterMemberCreateRequest]] = None  # optional initial members


class RouterUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    selector_model: Optional[str] = None
    selector_system_prompt: Optional[str] = None
    decompose_enabled: Optional[bool] = None
    routing_cache_enabled: Optional[bool] = None
    similarity_threshold: Optional[float] = None
    cache_ttl_hours: Optional[int] = None


class RouterQueryRequest(BaseModel):
    """Body for POST /routers/{id}/query and /preview (Phase 2 endpoints)."""
    question: str
    hints: Optional[List[str]] = None
    session_id: Optional[str] = None
