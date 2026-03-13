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
from app.services.database import db_service
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

        cached_queries = db_service.get_all_cached_queries(request.identity, runtime_settings)
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


@router.get("/debug/config")
async def debug_config(req: Request):
    """Debug endpoint to see configuration and headers. Disabled in production."""
    import os

    if settings.is_production:
        raise HTTPException(status_code=403, detail="Debug endpoint disabled in production")

    env_vars = {
        "DATABRICKS_HOST": settings.databricks_host or os.getenv("DATABRICKS_HOST") or "NOT SET",
        "DATABRICKS_TOKEN": ("***" + settings.databricks_token[-4:]) if settings.databricks_token else "NOT SET",
        "DATABRICKS_CLIENT_ID": os.getenv("DATABRICKS_CLIENT_ID") or "NOT SET",
        "DATABRICKS_CLIENT_SECRET": "***MASKED***" if os.getenv("DATABRICKS_CLIENT_SECRET") else "NOT SET",
        "APP_ENV": settings.app_env or "NOT SET",
        "STORAGE_BACKEND": settings.storage_backend or "NOT SET",
    }

    headers = {
        "X-Forwarded-Access-Token": ("***" + req.headers.get("X-Forwarded-Access-Token", "")[-4:]) if req.headers.get("X-Forwarded-Access-Token") else "NOT SET (local dev)",
        "X-Forwarded-Email": req.headers.get("X-Forwarded-Email") or "NOT SET (local dev)",
        "X-Forwarded-Host": req.headers.get("X-Forwarded-Host") or "NOT SET (local dev)",
        "Host": req.headers.get("Host", "NOT SET"),
    }

    config_values = {
        "databricks_host": settings.databricks_host or "EMPTY",
        "databricks_token_set": bool(settings.databricks_token),
        "genie_space_id": settings.genie_space_id or "EMPTY",
        "sql_warehouse_id": settings.sql_warehouse_id or "EMPTY",
        "app_env": settings.app_env,
        "storage_backend": settings.storage_backend,
        "lakebase_instance": settings.lakebase_instance or "NOT SET",
    }

    return {
        "environment_variables": env_vars,
        "request_headers": headers,
        "config_values": config_values,
        "timestamp": datetime.now().isoformat()
    }


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

        log_id = db_service.save_query_log(
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

        logs = db_service.get_query_logs(
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
