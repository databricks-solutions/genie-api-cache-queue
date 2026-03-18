"""
API routes for the Genie Cache application.
"""

import logging
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
from app.services.query_processor import query_processor
from app.services.queue_service import queue_service
import app.services.database as _db
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


@router.post("/query", response_model=QueryResponse)
async def submit_query(request: QueryRequest, req: Request):
    """Submit a new query for processing."""
    try:
        logger.info("Submit query: %r identity=%s auth=%s",
                     request.query[:50], request.identity,
                     request.config.auth_mode if request.config else "default")

        user_token = req.headers.get('X-Forwarded-Access-Token')
        user_email = req.headers.get('X-Forwarded-Email')

        query_id = query_processor.submit_query(
            request.query,
            request.identity,
            runtime_config=request.config,
            user_token=user_token,
            user_email=user_email,
            conversation_id=request.conversation_id,
            conversation_synced=request.conversation_synced,
            conversation_history=request.conversation_history,
        )

        return QueryResponse(
            query_id=query_id,
            stage=QueryStage.RECEIVED,
            message="Query submitted successfully"
        )
    except Exception as e:
        logger.exception("Error submitting query")
        raise HTTPException(status_code=500, detail=str(e))


class StatusRequest(BaseModel):
    config: Optional[RuntimeConfig] = None

@router.post("/query/{query_id}/status", response_model=QueryStatus)
async def get_query_status_post(query_id: str, request: Optional[StatusRequest] = None):
    """Get the status of a specific query."""
    status = queue_service.get_query_status(query_id)

    if not status:
        raise HTTPException(status_code=404, detail=f"Query {query_id} not found")

    return QueryStatus(**status)


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
    genie_space_id: Optional[str] = None
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
            request.genie_space_id,
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
                genie_space_id=log.get('genie_space_id'),
                created_at=datetime.fromisoformat(log['created_at'])
            )
            for log in logs
        ]
    except Exception as e:
        logger.warning("Error getting query logs: %s", e)
        return []


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }


# --- Unified config endpoints (accessible by frontend without Bearer token) ---

from app.api.config_store import get_effective_setting, update_overrides, get_overrides


class UIConfigUpdate(BaseModel):
    auth_mode: Optional[str] = None
    lakebase_service_token: Optional[str] = None
    user_pat: Optional[str] = None
    genie_space_id: Optional[str] = None
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


@router.get("/config")
async def get_config():
    """Get server configuration. Used by Settings UI and external API."""
    overrides = get_overrides()
    ttl_hours = get_effective_setting("cache_ttl_hours") or 0
    ttl_seconds = int(ttl_hours * 3600)
    return {
        "auth_mode": overrides.get("auth_mode", "app"),
        "genie_space_id": get_effective_setting("genie_space_id"),
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
        "lakebase_service_token_set": bool(get_effective_setting("lakebase_service_token")),
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
        elif field == "user_pat":
            batch["lakebase_service_token"] = value
            updated["lakebase_service_token"] = "***"
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


@router.delete("/cache")
async def clear_cache(req: Request):
    """Delete all cached queries from Lakebase."""
    try:
        overrides = get_overrides()
        rc = RuntimeConfig(
            auth_mode=overrides.get("auth_mode", "app"),
            storage_backend="lakebase" if get_effective_setting("storage_backend") in ("pgvector", "lakebase") else "local",
            lakebase_instance_name=get_effective_setting("lakebase_instance_name") or settings.lakebase_instance or None,
            lakebase_schema=get_effective_setting("lakebase_schema") or settings.lakebase_schema or "public",
            cache_table_name=get_effective_setting("cache_table_name") or settings.pgvector_table_name or "cached_queries",
        )
        user_token = req.headers.get('X-Forwarded-Access-Token')
        user_email = req.headers.get('X-Forwarded-Email')
        rs = RuntimeSettings(rc, user_token, user_email)
        count = await _db.db_service.clear_cache(rs)
        return {"success": True, "deleted": count, "message": f"Cache cleared ({count} entries deleted)"}
    except Exception as e:
        logger.exception("Error clearing cache")
        raise HTTPException(status_code=500, detail=str(e))


