"""
External proxy API for Genie Cache & Queue.
Exposes a REST API that external applications can call instead of the Genie API
directly, getting transparent caching, queueing, and rate-limit management.
Callers authenticate with their own PAT or OAuth token via Authorization header.
"""

import logging
import asyncio
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app.models import (
    ProxyQueryRequest,
    ProxyQueryResponse,
    ProxyQueryStatusResponse,
    RuntimeConfig,
)
from app.services.query_processor import query_processor
from app.services.queue_service import queue_service
import app.services.database as _db
from app.config import get_settings
from app.api.config_store import (
    get_effective_setting as _get_effective_setting,
    _server_config_overrides,
    update_overrides,
    get_overrides,
)
from app.api.auth_helpers import (
    extract_bearer_token,
    build_simple_runtime_settings,
    ttl_hours_to_seconds,
    ttl_seconds_to_hours,
)

logger = logging.getLogger(__name__)
settings = get_settings()

proxy_router = APIRouter()

SYNC_TIMEOUT_SECONDS = 120
SYNC_POLL_INTERVAL = 1.0


def _build_runtime_config(token: str, body: ProxyQueryRequest) -> RuntimeConfig:
    """Build a RuntimeConfig from caller token + request params + server config."""
    return RuntimeConfig(
        auth_mode="user",
        user_pat=token,
        genie_space_id=body.space_id or _get_effective_setting("genie_space_id") or None,
        sql_warehouse_id=body.warehouse_id or _get_effective_setting("sql_warehouse_id") or None,
        similarity_threshold=_get_effective_setting("similarity_threshold"),
        max_queries_per_minute=_get_effective_setting("max_queries_per_minute"),
        cache_ttl_hours=_get_effective_setting("cache_ttl_hours"),
        embedding_provider=_get_effective_setting("embedding_provider"),
        databricks_embedding_endpoint=settings.databricks_embedding_endpoint,
        storage_backend="lakebase" if settings.storage_backend == "pgvector" else settings.storage_backend,
        lakebase_instance_name=settings.lakebase_instance or None,
        lakebase_catalog=settings.lakebase_catalog or None,
        lakebase_schema=settings.lakebase_schema or None,
        cache_table_name=settings.pgvector_table_name or None,
        shared_cache=_server_config_overrides.get("shared_cache", True),
    )


def _map_status(raw_status: dict) -> ProxyQueryStatusResponse:
    """Map internal query status to the proxy API response model."""
    stage = raw_status.get("stage", "unknown")

    if stage in ("received", "checking_cache", "cache_hit", "cache_miss", "processing_genie", "executing_sql"):
        status = "processing"
    elif stage == "queued":
        status = "queued"
    elif stage == "completed":
        status = "completed"
    elif stage == "failed":
        status = "failed"
    else:
        status = stage

    return ProxyQueryStatusResponse(
        query_id=raw_status.get("query_id", ""),
        status=status,
        stage=stage,
        sql_query=raw_status.get("sql_query"),
        result=raw_status.get("result"),
        from_cache=raw_status.get("from_cache", False),
        error=raw_status.get("error"),
        conversation_id=raw_status.get("conversation_id"),
    )


def _validate_required_ids(runtime_config: RuntimeConfig):
    """Validate that space_id and warehouse_id are present."""
    if not runtime_config.genie_space_id:
        raise HTTPException(
            status_code=400,
            detail="space_id is required (either in the request body or configured as server default)",
        )
    if not runtime_config.sql_warehouse_id:
        raise HTTPException(
            status_code=400,
            detail="warehouse_id is required (either in the request body or configured as server default)",
        )


@proxy_router.post("/query", response_model=ProxyQueryResponse)
async def proxy_submit_query(body: ProxyQueryRequest, request: Request):
    """Submit a query for async processing. Poll GET /query/{query_id} for results."""
    token = extract_bearer_token(request)
    runtime_config = _build_runtime_config(token, body)
    _validate_required_ids(runtime_config)

    identity = (body.identity
                or request.headers.get("X-Forwarded-Email")
                or "api-user")

    try:
        query_id = query_processor.submit_query(
            query_text=body.query,
            identity=identity,
            runtime_config=runtime_config,
            user_token=None,
            user_email=request.headers.get("X-Forwarded-Email"),
            conversation_id=body.conversation_id,
            conversation_synced=bool(body.conversation_id),
            conversation_history=None,
        )
        return ProxyQueryResponse(query_id=query_id, status="received")
    except Exception as e:
        logger.exception("Error submitting proxy query")
        raise HTTPException(status_code=500, detail=str(e))


@proxy_router.get("/query/{query_id}", response_model=ProxyQueryStatusResponse)
async def proxy_get_query_status(query_id: str, request: Request):
    """Poll the status and result of a submitted query."""
    extract_bearer_token(request)

    raw = queue_service.get_query_status(query_id)
    if not raw:
        raise HTTPException(status_code=404, detail=f"Query {query_id} not found")

    return _map_status(raw)


@proxy_router.post("/query/sync", response_model=ProxyQueryStatusResponse)
async def proxy_submit_query_sync(body: ProxyQueryRequest, request: Request):
    """Submit a query and wait for the result (blocking, up to 120s timeout)."""
    token = extract_bearer_token(request)
    runtime_config = _build_runtime_config(token, body)
    _validate_required_ids(runtime_config)

    identity = (body.identity
                or request.headers.get("X-Forwarded-Email")
                or "api-user")

    try:
        query_id = query_processor.submit_query(
            query_text=body.query,
            identity=identity,
            runtime_config=runtime_config,
            user_token=None,
            user_email=request.headers.get("X-Forwarded-Email"),
            conversation_id=body.conversation_id,
            conversation_synced=bool(body.conversation_id),
            conversation_history=None,
        )
    except Exception as e:
        logger.exception("Error submitting sync proxy query")
        raise HTTPException(status_code=500, detail=str(e))

    elapsed = 0.0
    while elapsed < SYNC_TIMEOUT_SECONDS:
        await asyncio.sleep(SYNC_POLL_INTERVAL)
        elapsed += SYNC_POLL_INTERVAL

        raw = queue_service.get_query_status(query_id)
        if not raw:
            continue

        stage = raw.get("stage", "")
        if stage in ("completed", "failed"):
            return _map_status(raw)

    raw = queue_service.get_query_status(query_id) or {}
    response = _map_status(raw) if raw else ProxyQueryStatusResponse(
        query_id=query_id, status="timeout", error=f"Query timed out after {SYNC_TIMEOUT_SECONDS} seconds"
    )
    if response.status not in ("completed", "failed"):
        response.status = "timeout"
        response.error = response.error or f"Query timed out after {SYNC_TIMEOUT_SECONDS} seconds"
    return response


@proxy_router.get("/health")
async def proxy_health():
    """Health check for the proxy API."""
    return {
        "status": "healthy",
        "service": "genie-cache-queue-api",
        "timestamp": datetime.now().isoformat(),
    }


# --- Management endpoints ---

@proxy_router.get("/cache")
async def proxy_list_cache(request: Request):
    """List all cached queries."""
    token = extract_bearer_token(request)
    rs = build_simple_runtime_settings(token)
    identity = request.headers.get("X-Forwarded-Email")

    try:
        cached = await _db.db_service.get_all_cached_queries(identity, rs)
        return cached
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@proxy_router.get("/queue")
async def proxy_list_queue(request: Request):
    """List all queued queries."""
    extract_bearer_token(request)
    try:
        return queue_service.get_all_queued()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@proxy_router.get("/query-logs")
async def proxy_get_query_logs(request: Request):
    """List recent query logs (last 50)."""
    token = extract_bearer_token(request)
    rs = build_simple_runtime_settings(token)
    identity = request.headers.get("X-Forwarded-Email")

    try:
        logs = await _db.db_service.get_query_logs(identity=identity, limit=50, runtime_settings=rs)
        return logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SaveQueryLogBody(BaseModel):
    query_id: str
    query_text: str
    identity: str
    stage: str
    from_cache: bool = False
    genie_space_id: Optional[str] = None


@proxy_router.post("/query-logs")
async def proxy_save_query_log(body: SaveQueryLogBody, request: Request):
    """Save a query log entry."""
    token = extract_bearer_token(request)
    rs = build_simple_runtime_settings(token)

    try:
        log_id = await _db.db_service.save_query_log(
            body.query_id, body.query_text, body.identity,
            body.stage, body.from_cache, body.genie_space_id, rs,
        )
        return {"success": True, "log_id": log_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


class ServerConfigUpdate(BaseModel):
    genie_space_id: Optional[str] = None
    genie_spaces: Optional[list] = None  # List of {"id": "...", "name": "..."}
    sql_warehouse_id: Optional[str] = None
    similarity_threshold: Optional[float] = None
    max_queries_per_minute: Optional[int] = None
    cache_ttl_seconds: Optional[int] = None
    shared_cache: Optional[bool] = None
    embedding_provider: Optional[str] = None
    databricks_embedding_endpoint: Optional[str] = None
    storage_backend: Optional[str] = None
    lakebase_instance_name: Optional[str] = None
    lakebase_catalog: Optional[str] = None
    lakebase_schema: Optional[str] = None
    cache_table_name: Optional[str] = None
    query_log_table_name: Optional[str] = None


@proxy_router.get("/config")
async def proxy_get_config(request: Request):
    """Get current server configuration."""
    extract_bearer_token(request)
    overrides = get_overrides()
    ttl_hours = _get_effective_setting("cache_ttl_hours") or 0
    return {
        "genie_space_id": _get_effective_setting("genie_space_id"),
        "genie_spaces": _get_effective_setting("genie_spaces") or [],
        "sql_warehouse_id": _get_effective_setting("sql_warehouse_id"),
        "similarity_threshold": _get_effective_setting("similarity_threshold"),
        "max_queries_per_minute": _get_effective_setting("max_queries_per_minute"),
        "cache_ttl_seconds": ttl_hours_to_seconds(ttl_hours),
        "shared_cache": overrides.get("shared_cache", True),
        "embedding_provider": _get_effective_setting("embedding_provider"),
        "databricks_embedding_endpoint": _get_effective_setting("databricks_embedding_endpoint"),
        "storage_backend": _get_effective_setting("storage_backend"),
        "lakebase_instance_name": settings.lakebase_instance or overrides.get("lakebase_instance_name"),
        "lakebase_catalog": settings.lakebase_catalog or overrides.get("lakebase_catalog"),
        "lakebase_schema": settings.lakebase_schema or overrides.get("lakebase_schema"),
        "cache_table_name": settings.pgvector_table_name or overrides.get("cache_table_name"),
        "query_log_table_name": overrides.get("query_log_table_name", "query_logs"),
        "databricks_host": settings.databricks_host or None,
    }


@proxy_router.put("/config")
async def proxy_update_config(body: ServerConfigUpdate, request: Request):
    """Update server configuration (in-memory, persists for app lifetime)."""
    extract_bearer_token(request)
    updated = {}
    batch = {}
    for field, value in body.model_dump(exclude_none=True).items():
        if field == "cache_ttl_seconds":
            batch["cache_ttl_hours"] = ttl_seconds_to_hours(value)
            updated["cache_ttl_seconds"] = value
        else:
            batch[field] = value
            updated[field] = value

    if not updated:
        raise HTTPException(status_code=400, detail="No fields to update. Send at least one field.")

    update_overrides(batch)

    logger.info("Config updated via API: %s", updated)
    return {"updated": updated, "message": "Configuration updated successfully"}
