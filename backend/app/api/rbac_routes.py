"""RBAC management endpoints for user/role administration."""

import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import ensure_https
from app.api.auth_helpers import extract_bearer_token_optional
from app.api.config_store import get_effective_setting
from app.config import get_settings
from app.services.rbac import resolve_role, role_gte, ROLES, invalidate_role_cache

logger = logging.getLogger(__name__)
rbac_router = APIRouter()
_settings = get_settings()


def _get_host() -> str:
    host = get_effective_setting("databricks_host") or _settings.databricks_host or ""
    return ensure_https(host) if host else host


async def _resolve_caller(req: Request):
    """Extract and resolve the calling user's identity and effective role.

    When user token passthrough is disabled in Databricks Apps, the user's
    OAuth token is unavailable.  We still identify the user via the
    X-Forwarded-Email header (always present for SSO-authenticated users)
    and resolve their role from the database.  The SCIM workspace-admin
    check is skipped (requires the user's own token).
    """
    identity = req.headers.get("X-Forwarded-Email", "")
    token = extract_bearer_token_optional(req)

    if not token and not identity:
        raise HTTPException(
            status_code=401,
            detail="No authentication token or user identity available.",
        )

    role = await resolve_role(identity, token, _get_host())
    return identity, token, role


async def _require_role(req: Request, min_role: str):
    identity, token, role = await _resolve_caller(req)
    if not role_gte(role, min_role):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{min_role}' required. You have '{role}'."
        )
    return identity, token, role


@rbac_router.get("/users/me")
async def get_my_role(req: Request):
    """Return the current user's identity and effective role."""
    identity, _, role = await _resolve_caller(req)
    return {"identity": identity, "role": role}


@rbac_router.get("/users")
async def list_users(req: Request):
    """List all explicit role assignments. Manage or above."""
    await _require_role(req, "manage")
    import app.services.database as _db
    return await _db.db_service.list_user_roles()


class RoleAssignment(BaseModel):
    role: str


@rbac_router.post("/users/{email}/role", status_code=200)
async def assign_role(email: str, body: RoleAssignment, req: Request):
    """Assign a role to a user. Manage or above."""
    identity, _, _ = await _require_role(req, "manage")
    if body.role not in ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{body.role}'. Valid roles: {ROLES}"
        )
    import app.services.database as _db
    await _db.db_service.set_user_role(email, body.role, granted_by=identity)
    invalidate_role_cache(email)
    logger.info("Role assigned: %s → %s by %s", email, body.role, identity)
    return {"identity": email, "role": body.role}


@rbac_router.delete("/users/{email}")
async def remove_user_role(email: str, req: Request):
    """Remove explicit role assignment (reverts to default 'use'). Manage or above."""
    identity, _, _ = await _require_role(req, "manage")
    import app.services.database as _db
    await _db.db_service.delete_user_role(email)
    invalidate_role_cache(email)
    logger.info("Role removed: %s by %s", email, identity)
    return {"success": True}
