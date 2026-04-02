"""
Gateway CRUD API routes.
Manages gateway configurations and provides workspace discovery endpoints.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.auth import ensure_https
from app.models import GatewayConfig, GatewayCreateRequest, GatewayUpdateRequest
from app.api.auth_helpers import extract_bearer_token
from app.api.config_store import get_effective_setting, get_overrides, update_overrides
from app.config import get_settings
import app.services.database as _db
from app.services.rbac import resolve_role, role_gte

logger = logging.getLogger(__name__)
gateway_router = APIRouter()
settings = get_settings()



async def _require_role(req: Request, min_role: str):
    """Resolve caller's effective role and raise 403 if below min_role.
    Uses extract_bearer_token (user OBO token only — no service-token fallback).
    """
    token = extract_bearer_token(req)
    identity = req.headers.get("X-Forwarded-Email", "")
    host = _get_host()
    role = await resolve_role(identity, token, host)
    if not role_gte(role, min_role):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{min_role}' required. You have '{role}'."
        )


def _get_host() -> str:
    """Get Databricks workspace host with https:// prefix."""
    host = get_effective_setting("databricks_host") or settings.databricks_host
    if not host:
        raise HTTPException(status_code=500, detail="DATABRICKS_HOST not configured")
    return ensure_https(host)


# --- Gateway CRUD ---

@gateway_router.get("/gateways")
async def list_gateways():
    """List all gateways with stats."""
    try:
        gateways = await _db.db_service.list_gateways()
        # Attach stats to each gateway
        for gw in gateways:
            try:
                stats = await _db.db_service.get_gateway_stats(gw["id"])
                gw["cache_entries"] = stats.get("cache_count", 0)
                gw["query_count_7d"] = stats.get("query_count_7d", 0)
            except Exception:
                gw["cache_entries"] = 0
                gw["query_count_7d"] = 0
        return gateways
    except Exception as e:
        logger.exception("Error listing gateways")
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.post("/gateways", status_code=201)
async def create_gateway(body: GatewayCreateRequest, req: Request):
    """Create a new gateway configuration. Owner only."""
    await _require_role(req, "owner")
    try:
        now = datetime.now(timezone.utc)
        user_email = req.headers.get("X-Forwarded-Email")

        # Validate unique name
        existing = await _db.db_service.list_gateways()
        if any(g["name"].lower() == body.name.lower() for g in existing):
            raise HTTPException(status_code=409, detail=f"A gateway named '{body.name}' already exists.")

        config = {
            "id": str(uuid.uuid4()),
            "name": body.name,
            "genie_space_id": body.genie_space_id,
            "sql_warehouse_id": body.sql_warehouse_id,
            "similarity_threshold": body.similarity_threshold if body.similarity_threshold is not None else 0.92,
            "max_queries_per_minute": body.max_queries_per_minute if body.max_queries_per_minute is not None else 5,
            "cache_ttl_hours": body.cache_ttl_hours if body.cache_ttl_hours is not None else 24,
            "question_normalization_enabled": body.question_normalization_enabled if body.question_normalization_enabled is not None else True,
            "cache_validation_enabled": body.cache_validation_enabled if body.cache_validation_enabled is not None else True,
            "embedding_provider": body.embedding_provider or "databricks",
            "databricks_embedding_endpoint": body.databricks_embedding_endpoint or "databricks-gte-large-en",
            "shared_cache": body.shared_cache if body.shared_cache is not None else True,
            "status": "active",
            "created_by": user_email,
            "description": body.description or "",
            "created_at": now,
            "updated_at": now,
        }

        result = await _db.db_service.create_gateway(config)
        logger.info("Gateway created: id=%s name=%s by=%s", config["id"], config["name"], user_email)
        return result
    except Exception as e:
        logger.exception("Error creating gateway")
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.get("/gateways/{gateway_id}")
async def get_gateway(gateway_id: str):
    """Get a single gateway with stats."""
    try:
        gw = await _db.db_service.get_gateway(gateway_id)
        if not gw:
            raise HTTPException(status_code=404, detail="Gateway not found")

        try:
            stats = await _db.db_service.get_gateway_stats(gateway_id)
            gw["cache_entries"] = stats.get("cache_count", 0)
            gw["query_count_7d"] = stats.get("query_count_7d", 0)
        except Exception:
            gw["cache_entries"] = 0
            gw["query_count_7d"] = 0

        return gw
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting gateway")
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.put("/gateways/{gateway_id}")
async def update_gateway(gateway_id: str, body: GatewayUpdateRequest, req: Request):
    """Update gateway fields. Manage or above."""
    await _require_role(req, "manage")
    try:
        updates = body.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        result = await _db.db_service.update_gateway(gateway_id, updates)
        if not result:
            raise HTTPException(status_code=404, detail="Gateway not found")

        logger.info("Gateway updated: id=%s fields=%s", gateway_id, list(updates.keys()))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating gateway")
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.delete("/gateways/{gateway_id}")
async def delete_gateway(gateway_id: str, req: Request):
    """Delete a gateway. Owner only."""
    await _require_role(req, "owner")
    try:
        deleted = await _db.db_service.delete_gateway(gateway_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Gateway not found")

        logger.info("Gateway deleted: id=%s", gateway_id)
        return {"success": True, "message": f"Gateway {gateway_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting gateway")
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.get("/gateways/{gateway_id}/metrics")
async def get_gateway_metrics(gateway_id: str):
    """Get cache entries and query stats for a gateway."""
    try:
        gw = await _db.db_service.get_gateway(gateway_id)
        if not gw:
            raise HTTPException(status_code=404, detail="Gateway not found")

        stats = await _db.db_service.get_gateway_stats(gateway_id)
        cache_entries = stats.get("cache_count", 0)
        total_queries = stats.get("query_count_7d", 0)
        cache_hits = stats.get("cache_hits_7d", 0)
        hit_rate = (cache_hits / total_queries) if total_queries > 0 else 0.0
        return {
            "gateway_id": gateway_id,
            "cache_entries": cache_entries,
            "cache_count": cache_entries,  # legacy alias
            "total_queries": total_queries,
            "query_count_7d": total_queries,
            "cache_hits": cache_hits,
            "cache_hit_rate": hit_rate,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting gateway metrics")
        raise HTTPException(status_code=500, detail=str(e))


# --- Gateway-scoped cache & logs ---

@gateway_router.get("/gateways/{gateway_id}/cache")
async def get_gateway_cache(gateway_id: str):
    """List all cached entries for a specific gateway."""
    try:
        gw = await _db.db_service.get_gateway(gateway_id)
        if not gw:
            raise HTTPException(status_code=404, detail="Gateway not found")
        entries = await _db.db_service.get_all_cached_queries(identity=None, runtime_settings=None, gateway_id=gateway_id)
        return entries
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error listing gateway cache")
        raise HTTPException(status_code=500, detail=str(e))



@gateway_router.delete("/gateways/{gateway_id}/cache")
async def clear_gateway_cache(gateway_id: str, req: Request):
    """Clear all cached entries for a specific gateway. Manage or above."""
    await _require_role(req, "manage")
    try:
        gw = await _db.db_service.get_gateway(gateway_id)
        if not gw:
            raise HTTPException(status_code=404, detail="Gateway not found")
        count = await _db.db_service.clear_cache(runtime_settings=None, gateway_id=gateway_id)
        logger.info("Cache cleared for gateway %s: %d entries removed", gateway_id, count)
        return {"deleted": count, "gateway_id": gateway_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error clearing gateway cache")
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.get("/gateways/{gateway_id}/logs")
async def get_gateway_logs(gateway_id: str, limit: int = 50):
    """List query logs for a specific gateway."""
    try:
        gw = await _db.db_service.get_gateway(gateway_id)
        if not gw:
            raise HTTPException(status_code=404, detail="Gateway not found")
        logs = await _db.db_service.get_query_logs(identity=None, limit=limit, gateway_id=gateway_id)
        return logs
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error listing gateway logs")
        raise HTTPException(status_code=500, detail=str(e))


# --- Workspace discovery endpoints ---

@gateway_router.get("/workspace/genie-spaces")
async def list_genie_spaces(req: Request):
    """List available Genie Spaces from the workspace."""
    try:
        token = extract_bearer_token(req)
        host = _get_host()

        url = f"{host}/api/2.0/genie/spaces"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code != 200:
                logger.warning("Genie spaces API returned %d: %s", resp.status_code, resp.text[:200])
                raise HTTPException(status_code=resp.status_code, detail=f"Databricks API error: {resp.text}")
            return resp.json()
    except HTTPException:
        raise
    except httpx.HTTPError as e:
        logger.exception("Failed to reach Genie Spaces API")
        raise HTTPException(status_code=502, detail=f"Failed to reach Databricks API: {e}")
    except Exception as e:
        logger.exception("Error listing Genie spaces")
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.get("/workspace/warehouses")
async def list_warehouses(req: Request):
    """List available SQL warehouses from the workspace."""
    try:
        token = extract_bearer_token(req)
        host = _get_host()

        url = f"{host}/api/2.0/sql/warehouses"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code != 200:
                logger.warning("Warehouses API returned %d: %s", resp.status_code, resp.text[:200])
                raise HTTPException(status_code=resp.status_code, detail=f"Databricks API error: {resp.text}")
            return resp.json()
    except HTTPException:
        raise
    except httpx.HTTPError as e:
        logger.exception("Failed to reach Warehouses API")
        raise HTTPException(status_code=502, detail=f"Failed to reach Databricks API: {e}")
    except Exception as e:
        logger.exception("Error listing warehouses")
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.get("/workspace/serving-endpoints")
async def list_serving_endpoints(req: Request):
    """List available serving endpoints from the workspace."""
    try:
        token = extract_bearer_token(req)
        host = _get_host()

        url = f"{host}/api/2.0/serving-endpoints"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code != 200:
                logger.warning("Serving endpoints API returned %d: %s", resp.status_code, resp.text[:200])
                raise HTTPException(status_code=resp.status_code, detail=f"Databricks API error: {resp.text}")
            data = resp.json()
            endpoints = data.get("endpoints", [])
            # Return simplified list with name, task, state
            return {
                "endpoints": [
                    {
                        "name": ep.get("name", ""),
                        "task": ep.get("task", ""),
                        "state": ep.get("state", {}).get("ready", "UNKNOWN"),
                    }
                    for ep in endpoints
                    if ep.get("state", {}).get("ready") == "READY"
                ]
            }
    except HTTPException:
        raise
    except httpx.HTTPError as e:
        logger.exception("Failed to reach Serving Endpoints API")
        raise HTTPException(status_code=502, detail=f"Failed to reach Databricks API: {e}")
    except Exception as e:
        logger.exception("Error listing serving endpoints")
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.post("/settings/test-connection")
async def test_lakebase_connection():
    """Test Lakebase connection and check if required tables exist."""
    results = {
        "connected": False,
        "cache_table_exists": False,
        "query_log_table_exists": False,
        "gateway_table_exists": False,
        "error": None,
    }
    try:
        # db_service is DatabaseService which wraps _storage_backend (DynamicStorageService)
        import app.services.database as _db_module
        dynamic = _db_module._storage_backend
        if dynamic is None:
            results["error"] = "Storage backend not initialized."
            return results

        backend = dynamic.default_backend
        if not hasattr(backend, 'pool') or backend.pool is None:
            results["error"] = "Lakebase pool not available. Check instance name and credentials."
            return results

        # If pool is closed, try to reinitialize
        if backend.pool._closed:
            try:
                await backend.initialize()
            except Exception as e:
                results["error"] = f"Reconnect failed: {e}"
                return results

        async with backend.pool.acquire() as conn:
            results["connected"] = True
            for attr, key in [
                ("table_name", "cache_table_exists"),
                ("query_log_table_name", "query_log_table_exists"),
                ("gateway_table_name", "gateway_table_exists"),
            ]:
                table = getattr(backend, attr, None)
                if not table:
                    continue
                parts = table.split(".")
                tbl = parts[-1]
                schema = parts[-2] if len(parts) >= 2 else "public"
                row = await conn.fetchrow(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema=$1 AND table_name=$2",
                    schema, tbl
                )
                results[key] = row is not None

        return results
    except Exception as e:
        results["error"] = str(e)
        return results


# --- Settings endpoints (reuse existing config_store) ---

@gateway_router.get("/settings")
async def get_settings_endpoint():
    """Return current server configuration."""
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
        "lakebase_service_token_set": bool(get_effective_setting("lakebase_service_token")),
        "question_normalization_enabled": overrides.get("question_normalization_enabled", True),
        "cache_validation_enabled": overrides.get("cache_validation_enabled", True),
    }


class SettingsUpdateRequest(GatewayUpdateRequest):
    """Settings update - reuses gateway fields plus additional config fields."""
    lakebase_service_token: Optional[str] = None
    genie_space_id: Optional[str] = None
    genie_spaces: Optional[list] = None
    sql_warehouse_id: Optional[str] = None
    cache_ttl_seconds: Optional[int] = None
    storage_backend: Optional[str] = None
    lakebase_instance_name: Optional[str] = None
    lakebase_catalog: Optional[str] = None
    lakebase_schema: Optional[str] = None
    cache_table_name: Optional[str] = None
    query_log_table_name: Optional[str] = None


@gateway_router.put("/settings")
async def update_settings_endpoint(body: SettingsUpdateRequest, req: Request):
    """Update server configuration. Owner only."""
    await _require_role(req, "owner")
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
    logger.info("Settings updated via gateway API: %s", updated)
    return {"updated": updated, "message": "Settings updated successfully"}
