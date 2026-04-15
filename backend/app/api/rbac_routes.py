"""RBAC management endpoints for user/role administration."""

import asyncio
import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.auth_helpers import extract_bearer_token_optional, require_role
from app.services.rbac import ROLES, role_gte, invalidate_role_cache

logger = logging.getLogger(__name__)
rbac_router = APIRouter()
# Serializes last-owner checks against role writes. Sufficient because
# Databricks Apps runs a single replica — no cross-instance coordination needed.
_owner_lock = asyncio.Lock()


@rbac_router.get("/users/me")
async def get_my_role(req: Request):
    """Return the current user's identity and effective role."""
    identity, _, role = await require_role(req, "use")
    return {"identity": identity, "role": role}


@rbac_router.get("/auth/mode")
async def get_auth_mode(req: Request):
    """Report whether the app is using user token passthrough or SP fallback."""
    token = extract_bearer_token_optional(req)
    if token:
        return {"auth_mode": "user", "message": "User token passthrough is active."}
    return {
        "auth_mode": "service_principal",
        "message": (
            "User token passthrough is disabled. Queries use the app's service principal. "
            "Grant the SP access to Genie Spaces and SQL Warehouses. "
            "Per-user access controls and lineage are not enforced."
        ),
    }


@rbac_router.get("/users")
async def list_users(req: Request):
    """List all explicit role assignments. Manage or above."""
    await require_role(req, "manage")
    import app.services.database as _db
    return await _db.db_service.list_user_roles()


class RoleAssignment(BaseModel):
    role: str


async def _check_last_owner(email: str, new_role: str = None):
    """Prevent removing or downgrading the last owner."""
    import app.services.database as _db
    target_role = await _db.db_service.get_user_role(email)
    if target_role == "owner" and new_role != "owner":
        owner_count = await _db.db_service.count_owners()
        if owner_count <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot remove or downgrade the last owner. Assign another owner first.",
            )


@rbac_router.post("/users/{email}/role", status_code=200)
async def assign_role(email: str, body: RoleAssignment, req: Request):
    """Assign a role to a user. Manage or above."""
    identity, _, caller_role = await require_role(req, "manage")
    if body.role not in ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{body.role}'. Valid roles: {ROLES}"
        )
    if not role_gte(caller_role, body.role):
        raise HTTPException(
            status_code=403,
            detail=f"Cannot assign role '{body.role}' — your role ('{caller_role}') is insufficient.",
        )
    import app.services.database as _db
    async with _owner_lock:
        await _check_last_owner(email, body.role)
        await _db.db_service.set_user_role(email, body.role, granted_by=identity)
    invalidate_role_cache(email)
    logger.info("Role assigned: %s → %s by %s", email, body.role, identity)
    return {"identity": email, "role": body.role, "granted_by": identity}


@rbac_router.delete("/users/{email}")
async def remove_user_role(email: str, req: Request):
    """Remove explicit role assignment (reverts to default 'use'). Manage or above."""
    identity, _, caller_role = await require_role(req, "manage")
    import app.services.database as _db
    async with _owner_lock:
        target_role = await _db.db_service.get_user_role(email)
        if target_role and not role_gte(caller_role, target_role):
            raise HTTPException(
                status_code=403,
                detail=f"Cannot remove a user with role '{target_role}' — your role ('{caller_role}') is insufficient.",
            )
        await _check_last_owner(email)
        await _db.db_service.delete_user_role(email)
    invalidate_role_cache(email)
    logger.info("Role removed: %s by %s", email, identity)
    return {"success": True}
