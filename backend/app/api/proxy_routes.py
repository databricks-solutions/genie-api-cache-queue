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

logger = logging.getLogger(__name__)
settings = get_settings()

proxy_router = APIRouter()

SYNC_TIMEOUT_SECONDS = 120
SYNC_POLL_INTERVAL = 1.0

# Server config overrides (in-memory, persists for app lifetime)
_server_config_overrides: dict = {}


def _get_effective_setting(key: str):
    """Get setting value: override > env/settings default."""
    if key in _server_config_overrides:
        return _server_config_overrides[key]
    return getattr(settings, key, None)


def _extract_bearer_token(request: Request) -> str:
    """Extract token for Genie API calls.

    Priority:
    1. X-Forwarded-Access-Token (Databricks Apps with user auth resource)
    2. Authorization: Bearer header (direct/local dev access)
    3. DATABRICKS_TOKEN env var (Databricks Apps proxy — user authenticated via OAuth,
       token consumed by proxy, app uses its own SP token for API calls)
    """
    forwarded_token = request.headers.get("X-Forwarded-Access-Token", "").strip()
    if forwarded_token:
        return forwarded_token

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return token

    # Databricks Apps: proxy authenticated the user but consumed the token.
    # Use the app's service principal credentials (CLIENT_ID + CLIENT_SECRET) to get a token.
    if request.headers.get("X-Forwarded-Email"):
        from app.auth import get_service_principal_token
        sp_token = get_service_principal_token()
        if sp_token:
            logger.info("Using app SP token for authenticated user %s",
                        request.headers.get("X-Forwarded-Email"))
            return sp_token

    raise HTTPException(
        status_code=401,
        detail="Missing authentication. Provide Authorization: Bearer <token> or access via Databricks Apps.",
    )


def _build_runtime_config(token: str, body: ProxyQueryRequest) -> RuntimeConfig:
    """Build a RuntimeConfig from caller token + request params + server config overrides + env defaults."""
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
    """Map internal query status dict to the proxy API response model."""
    stage = raw_status.get("stage", "unknown")
    # Map internal stages to simpler external statuses
    if stage in ("received", "checking_cache"):
        status = "processing"
    elif stage in ("cache_hit", "cache_miss", "processing_genie", "executing_sql"):
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
    """Submit a query for async processing. Poll GET /query/{query_id} for results."""
    token = _extract_bearer_token(request)
    runtime_config = _build_runtime_config(token, body)

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
    _extract_bearer_token(request)  # Validate auth

    raw = queue_service.get_query_status(query_id)
    if not raw:
        raise HTTPException(status_code=404, detail=f"Query {query_id} not found")

    return _map_status(raw)


@proxy_router.post("/query/sync", response_model=ProxyQueryStatusResponse)
async def proxy_submit_query_sync(body: ProxyQueryRequest, request: Request):
    """Submit a query and wait for the result (blocking, up to 120s timeout)."""
    token = _extract_bearer_token(request)
    runtime_config = _build_runtime_config(token, body)

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

    # Poll until terminal state or timeout
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

    # Timeout — return current state
    raw = queue_service.get_query_status(query_id) or {}
    response = _map_status(raw) if raw else ProxyQueryStatusResponse(
        query_id=query_id, status="timeout", error="Query timed out after 120 seconds"
    )
    if response.status not in ("completed", "failed"):
        response.status = "timeout"
        response.error = response.error or "Query timed out after 120 seconds"
    return response


@proxy_router.get("/health")
async def proxy_health():
    """Health check for the proxy API."""
    return {
        "status": "healthy",
        "service": "genie-cache-queue-api",
        "timestamp": datetime.now().isoformat(),
    }


@proxy_router.get("/debug/headers")
async def proxy_debug_headers(request: Request):
    """Debug endpoint to inspect request headers (disable in production)."""
    relevant = {}
    for key in request.headers.keys():
        lower = key.lower()
        if any(k in lower for k in ["auth", "forward", "token", "cookie", "x-"]):
            val = request.headers[key]
            if len(val) > 20 and ("token" in lower or "auth" in lower):
                relevant[key] = f"{val[:10]}...{val[-4:]}"
            else:
                relevant[key] = val
    return {"headers": relevant, "all_keys": list(request.headers.keys())}


# --- Management endpoints ---

@proxy_router.get("/cache")
async def proxy_list_cache(request: Request):
    """List all cached queries."""
    token = _extract_bearer_token(request)
    from app.runtime_config import RuntimeSettings
    rc = RuntimeConfig(auth_mode="user", user_pat=token)
    rs = RuntimeSettings(rc, None, None)
    identity = request.headers.get("X-Forwarded-Email")

    try:
        cached = await _db.db_service.get_all_cached_queries(identity, rs)
        return cached
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@proxy_router.get("/queue")
async def proxy_list_queue(request: Request):
    """List all queued queries."""
    _extract_bearer_token(request)
    try:
        return queue_service.get_all_queued()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@proxy_router.get("/query-logs")
async def proxy_get_query_logs(request: Request):
    """List recent query logs (last 50)."""
    token = _extract_bearer_token(request)
    from app.runtime_config import RuntimeSettings
    rc = RuntimeConfig(auth_mode="user", user_pat=token)
    rs = RuntimeSettings(rc, None, None)
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
    token = _extract_bearer_token(request)
    from app.runtime_config import RuntimeSettings
    rc = RuntimeConfig(auth_mode="user", user_pat=token)
    rs = RuntimeSettings(rc, None, None)

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
    sql_warehouse_id: Optional[str] = None
    similarity_threshold: Optional[float] = None
    max_queries_per_minute: Optional[int] = None
    cache_ttl_hours: Optional[float] = None
    embedding_provider: Optional[str] = None
    shared_cache: Optional[bool] = None


@proxy_router.get("/config")
async def proxy_get_config(request: Request):
    """Get current server configuration."""
    _extract_bearer_token(request)
    return {
        "genie_space_id": _get_effective_setting("genie_space_id"),
        "sql_warehouse_id": _get_effective_setting("sql_warehouse_id"),
        "similarity_threshold": _get_effective_setting("similarity_threshold"),
        "max_queries_per_minute": _get_effective_setting("max_queries_per_minute"),
        "cache_ttl_hours": _get_effective_setting("cache_ttl_hours"),
        "embedding_provider": _get_effective_setting("embedding_provider"),
        "storage_backend": _get_effective_setting("storage_backend"),
        "shared_cache": _server_config_overrides.get("shared_cache", True),
        "databricks_host": settings.databricks_host or None,
    }


@proxy_router.put("/config")
async def proxy_update_config(body: ServerConfigUpdate, request: Request):
    """Update server configuration (in-memory, persists for app lifetime)."""
    _extract_bearer_token(request)
    updated = {}
    for field, value in body.model_dump(exclude_none=True).items():
        _server_config_overrides[field] = value
        updated[field] = value

    if not updated:
        raise HTTPException(status_code=400, detail="No fields to update. Send at least one field.")

    logger.info("Config updated via API: %s", updated)
    return {"updated": updated, "message": "Configuration updated successfully"}
