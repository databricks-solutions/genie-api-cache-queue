"""
API routes for the Genie Cache application.
"""

import logging
import uuid
from fastapi import APIRouter, HTTPException, Request
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel
from app.models import (
    QueryRequest,
    QueryResponse,
    QueryStatus,
    CachedQuery,
    QueuedQuery,
    QueryLog,
    QueryStage,
    RuntimeConfig
)
from app.runtime_config import RuntimeSettings
from app.services.queue_service import queue_service
from app.api.genie_clone_routes import _handle_query, _synthetic_messages
import app.services.database as _db
from app.config import get_settings

_proxy_registry: dict[str, str] = {}

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


@router.post("/query", response_model=QueryResponse)
async def submit_query(request: QueryRequest, req: Request):
    try:
        token = req.headers.get("X-Forwarded-Access-Token") or ""
        identity = req.headers.get("X-Forwarded-Email") or ""

        if not identity:
            raise HTTPException(status_code=401, detail="X-Forwarded-Email header missing.")

        # Resolve gateway: config.genie_space_id may be a gateway UUID
        gateway = None
        space_id = request.config.genie_space_id if request.config else None
        if space_id:
            try:
                gw = await _db.db_service.get_gateway(space_id)
                if gw:
                    gateway = gw
                    space_id = gw["genie_space_id"]
            except Exception:
                pass

        if not space_id:
            raise HTTPException(status_code=400, detail="No gateway or space_id provided.")

        result = await _handle_query(
            space_id=space_id,
            query_text=request.query,
            token=token,
            identity=identity,
            gateway=gateway,
        )

        query_id = str(uuid.uuid4())
        msg_id = result.get("message_id")
        if not msg_id:
            raise HTTPException(status_code=500, detail="Internal error: no message_id returned")
        _proxy_registry[query_id] = msg_id

        return QueryResponse(query_id=query_id, stage=QueryStage.RECEIVED, message="Query submitted successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error submitting query")
        raise HTTPException(status_code=500, detail=str(e))


class StatusRequest(BaseModel):
    config: Optional[RuntimeConfig] = None

@router.post("/query/{query_id}/status", response_model=QueryStatus)
async def get_query_status_post(query_id: str, request: Optional[StatusRequest] = None):
    msg_id = _proxy_registry.get(query_id)
    if not msg_id:
        raise HTTPException(status_code=404, detail=f"Query {query_id} not found")

    msg = _synthetic_messages.get(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail=f"Query {query_id} not found")

    proxy = msg.get("_proxy", {})
    stage_str = proxy.get("stage", "received")
    from_cache = proxy.get("from_cache", False)
    sql_query = proxy.get("sql_query")
    result = proxy.get("result")
    error = msg.get("error")

    _stage_map = {
        "received":         QueryStage.RECEIVED,
        "checking_cache":   QueryStage.CHECKING_CACHE,
        "cache_hit":        QueryStage.CACHE_HIT,
        "cache_miss":       QueryStage.CACHE_MISS,
        "processing_genie": QueryStage.PROCESSING_GENIE,
        "executing_sql":    QueryStage.EXECUTING_SQL,
        "completed":        QueryStage.COMPLETED,
        "failed":           QueryStage.FAILED,
    }
    stage = _stage_map.get(stage_str, QueryStage.RECEIVED)

    return QueryStatus(
        query_id=query_id,
        stage=stage,
        from_cache=from_cache,
        sql_query=sql_query,
        result=result,
        error=str(error) if error else None,
    )


class CacheRequest(BaseModel):
    identity: Optional[str] = None
    config: Optional[RuntimeConfig] = None

@router.post("/cache", response_model=List[CachedQuery])
async def get_cache_post(request: CacheRequest, req: Request):
    """Get all cached queries."""
    try:
        user_token = req.headers.get('X-Forwarded-Access-Token')
        user_email = req.headers.get('X-Forwarded-Email')

        runtime_settings = RuntimeSettings(request.config, user_token, user_email) if request.config else None

        cached_queries = await _db.db_service.get_all_cached_queries(request.identity, runtime_settings)
        return cached_queries
    except Exception as e:
        logger.exception("Error in get_cache_post")
        raise HTTPException(status_code=500, detail=str(e))


class QueueRequest(BaseModel):
    config: Optional[RuntimeConfig] = None

@router.post("/queue", response_model=List[QueuedQuery])
async def get_queue_post(request: Optional[QueueRequest] = None):
    """Get all queued queries."""
    try:
        queued = queue_service.get_all_queued()
        return queued
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Query Logs Endpoints
class QueryLogRequest(BaseModel):
    identity: Optional[str] = None
    config: Optional[RuntimeConfig] = None


class SaveQueryLogRequest(BaseModel):
    query_id: str
    query_text: str
    identity: str
    stage: str
    from_cache: bool = False
    gateway_id: Optional[str] = None
    config: Optional[RuntimeConfig] = None


@router.post("/query-logs/save")
async def save_query_log_post(request: SaveQueryLogRequest, req: Request):
    """Save a query log entry"""
    try:
        user_token = req.headers.get('X-Forwarded-Access-Token')
        user_email = req.headers.get('X-Forwarded-Email')
        runtime_settings = RuntimeSettings(request.config, user_token, user_email) if request.config else None

        log_id = await _db.db_service.save_query_log(
            request.query_id,
            request.query_text,
            request.identity,
            request.stage,
            request.from_cache,
            request.gateway_id,
            runtime_settings
        )

        return {"success": True, "log_id": log_id}
    except Exception as e:
        logger.warning("Error saving query log: %s", e)
        return {"success": False, "error": str(e)}


@router.post("/query-logs", response_model=List[QueryLog])
async def get_query_logs_post(request: QueryLogRequest, req: Request):
    """Get query logs"""
    try:
        user_token = req.headers.get('X-Forwarded-Access-Token')
        user_email = req.headers.get('X-Forwarded-Email')
        runtime_settings = RuntimeSettings(request.config, user_token, user_email) if request.config else None

        logs = await _db.db_service.get_query_logs(
            identity=request.identity,
            limit=50,
            runtime_settings=runtime_settings
        )

        return [
            QueryLog(
                query_id=log['query_id'],
                query_text=log['query_text'],
                identity=log['identity'],
                stage=log['stage'],
                from_cache=log['from_cache'],
                gateway_id=log.get("gateway_id"),
                created_at=datetime.fromisoformat(log['created_at'])
            )
            for log in logs
        ]
    except Exception as e:
        logger.warning("Error getting query logs: %s", e)
        return []


@router.get("/health")
async def health_check(req: Request):
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "user_email": req.headers.get('X-Forwarded-Email'),
    }


@router.get("/space-info/{space_id}")
async def get_space_info(space_id: str, req: Request):
    """Fetch Genie Space metadata (name, description) using the caller's token."""
    import httpx

    token = req.headers.get('X-Forwarded-Access-Token') or settings.databricks_token
    if not token:
        raise HTTPException(status_code=401, detail="No token available to query Genie API")

    host = settings.databricks_host
    if not host:
        raise HTTPException(status_code=500, detail="DATABRICKS_HOST not configured")
    if not host.startswith("http"):
        host = f"https://{host}"

    url = f"{host}/api/2.0/genie/spaces/{space_id}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=f"Genie API error: {resp.text}")
            data = resp.json()
            return {
                "space_id": space_id,
                "name": data.get("display_name") or data.get("title") or data.get("name") or "",
                "description": data.get("description") or "",
            }
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Genie API: {e}")


# --- Unified config endpoints (accessible by frontend without Bearer token) ---

from app.api.config_store import get_effective_setting, update_overrides, get_overrides


class UIConfigUpdate(BaseModel):
    lakebase_service_token: Optional[str] = None
    gateway_id: Optional[str] = None
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
    question_normalization_enabled: Optional[bool] = None
    cache_validation_enabled: Optional[bool] = None


@router.get("/config")
async def get_config():
    """Get server configuration. Used by Settings UI and external API."""
    overrides = get_overrides()
    ttl_hours = get_effective_setting("cache_ttl_hours") or 0
    ttl_seconds = int(ttl_hours * 3600)
    return {
        "genie_space_id": get_effective_setting("genie_space_id"),
        "genie_spaces": get_effective_setting("genie_spaces") or [],
        "sql_warehouse_id": get_effective_setting("sql_warehouse_id"),
        "similarity_threshold": get_effective_setting("similarity_threshold"),
        "max_queries_per_minute": get_effective_setting("max_queries_per_minute"),
        "cache_ttl_seconds": ttl_seconds,
        "shared_cache": overrides.get("shared_cache", True),
        "embedding_provider": get_effective_setting("embedding_provider"),
        "databricks_embedding_endpoint": get_effective_setting("databricks_embedding_endpoint"),
        "storage_backend": get_effective_setting("storage_backend"),
        "lakebase_instance_name": settings.lakebase_instance or overrides.get("lakebase_instance_name"),
        "lakebase_catalog": settings.lakebase_catalog or overrides.get("lakebase_catalog"),
        "lakebase_schema": settings.lakebase_schema or overrides.get("lakebase_schema"),
        "cache_table_name": settings.pgvector_table_name or overrides.get("cache_table_name"),
        "query_log_table_name": overrides.get("query_log_table_name", "query_logs"),
        # True if any Lakebase token is available (custom override in memory OR auto-injected DATABRICKS_TOKEN)
        "lakebase_service_token_set": bool(get_effective_setting("lakebase_service_token") or settings.databricks_token),
        "lakebase_token_source": "override" if get_effective_setting("lakebase_service_token") else ("auto" if settings.databricks_token else "none"),
        "question_normalization_enabled": overrides.get("question_normalization_enabled", True),
        "cache_validation_enabled": overrides.get("cache_validation_enabled", True),
    }


@router.put("/config")
async def put_config(body: UIConfigUpdate):
    """Update server configuration. Used by Settings UI and external API."""
    batch = {}
    updated = {}
    for field, value in body.model_dump(exclude_none=True).items():
        if field == "cache_ttl_seconds":
            batch["cache_ttl_hours"] = value / 3600
            updated["cache_ttl_seconds"] = value
        elif field == "lakebase_service_token":
            batch[field] = value
            updated[field] = "***"
        else:
            batch[field] = value
            updated[field] = value

    if not updated:
        raise HTTPException(status_code=400, detail="No fields to update.")

    update_overrides(batch)
    logger.info("Config updated via UI: %s", updated)
    return {"updated": updated, "message": "Configuration updated successfully"}


@router.get("/cache/count")
async def cache_count(req: Request):
    """Return cache entry counts grouped by space_id."""
    try:
        overrides = get_overrides()
        rc = RuntimeConfig(
            storage_backend="lakebase" if get_effective_setting("storage_backend") in ("pgvector", "lakebase") else "local",
            lakebase_instance_name=get_effective_setting("lakebase_instance_name") or settings.lakebase_instance or None,
            lakebase_schema=get_effective_setting("lakebase_schema") or settings.lakebase_schema or "public",
            cache_table_name=get_effective_setting("cache_table_name") or settings.pgvector_table_name or "cached_queries",
        )
        user_token = req.headers.get('X-Forwarded-Access-Token')
        user_email = req.headers.get('X-Forwarded-Email')
        rs = RuntimeSettings(rc, user_token, user_email)
        result = await _db.db_service.get_cache_count(rs)
        return result
    except Exception as e:
        logger.exception("Error getting cache count")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cache")
async def clear_cache(req: Request, space_id: Optional[str] = None):
    """Delete cached queries, optionally filtered by space_id."""
    try:
        overrides = get_overrides()
        rc = RuntimeConfig(
            storage_backend="lakebase" if get_effective_setting("storage_backend") in ("pgvector", "lakebase") else "local",
            lakebase_instance_name=get_effective_setting("lakebase_instance_name") or settings.lakebase_instance or None,
            lakebase_schema=get_effective_setting("lakebase_schema") or settings.lakebase_schema or "public",
            cache_table_name=get_effective_setting("cache_table_name") or settings.pgvector_table_name or "cached_queries",
        )
        user_token = req.headers.get('X-Forwarded-Access-Token')
        user_email = req.headers.get('X-Forwarded-Email')
        rs = RuntimeSettings(rc, user_token, user_email)
        count = await _db.db_service.clear_cache(rs, gateway_id=space_id)
        label = f" for space {space_id}" if space_id else ""
        return {"success": True, "deleted": count, "message": f"Cache cleared{label} ({count} entries deleted)"}
    except Exception as e:
        logger.exception("Error clearing cache")
        raise HTTPException(status_code=500, detail=str(e))


