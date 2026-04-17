"""
External proxy API for Genie Cache & Queue.
Exposes a REST API that external applications can call instead of the Genie API
directly, getting transparent caching, queueing, and rate-limit management.
Callers authenticate with their own PAT or OAuth token via Authorization header.
"""

import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app.models import (
    ProxyQueryRequest,
    ProxyQueryResponse,
    ProxyQueryStatusResponse,
)
import app.services.database as _db
from app.config import get_settings
from app.api.config_store import (
    get_effective_setting as _get_effective_setting,
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



@proxy_router.post("/query", response_model=ProxyQueryResponse)
async def proxy_submit_query(body: ProxyQueryRequest, request: Request):
    """Submit a query for async processing. Poll GET /query/{query_id} for results.
    NOTE: Use the Genie Clone API (/api/2.0/genie/spaces/{space_id}/start-conversation) instead.
    """
    raise HTTPException(
        status_code=410,
        detail="This endpoint has been replaced. Use POST /api/2.0/genie/spaces/{space_id}/start-conversation instead.",
    )


@proxy_router.get("/query/{query_id}", response_model=ProxyQueryStatusResponse)
async def proxy_get_query_status(query_id: str, request: Request):
    """Poll the status and result of a submitted query.
    NOTE: Use the Genie Clone API (/api/2.0/genie/spaces/…/conversations/…/messages/{id}) instead.
    """
    extract_bearer_token(request)
    raise HTTPException(
        status_code=410,
        detail="This endpoint has been replaced. Use GET /api/2.0/genie/spaces/{space_id}/conversations/{conv_id}/messages/{msg_id} instead.",
    )


@proxy_router.post("/query/sync", response_model=ProxyQueryStatusResponse)
async def proxy_submit_query_sync(body: ProxyQueryRequest, request: Request):
    """Submit a query and wait for the result (blocking, up to 120s timeout).
    NOTE: Use the Genie Clone API (/api/2.0/genie/spaces/{space_id}/start-conversation) instead.
    """
    raise HTTPException(
        status_code=410,
        detail="This endpoint has been replaced. Use POST /api/2.0/genie/spaces/{space_id}/start-conversation instead.",
    )


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
    """List all queued queries. Queue has been replaced by direct background processing."""
    extract_bearer_token(request)
    return []


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
    """Update server configuration (persisted to Lakebase; survives redeploys)."""
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

    # Prefer the Databricks-Apps-injected caller email for audit parity with the
    # UI / gateway endpoints; fall back to "proxy-api" for non-header callers.
    updated_by = request.headers.get("X-Forwarded-Email") or "proxy-api"
    await update_overrides(batch, updated_by=updated_by)

    logger.info("Config updated via API: %s", updated)
    return {"updated": updated, "message": "Configuration updated successfully"}
