"""
Role-based access control for Genie Cache Gateway.

Roles (lowest → highest privilege):
  use     — query only: submit questions, view results
  manage  — configure gateways, view/clear cache; cannot create/delete gateways or manage users
  owner   — full control: create/delete gateways, manage users, configure settings

Workspace admins are always treated as owner regardless of the user_roles table.
Unassigned users default to 'use'.
"""

import logging
import httpx

logger = logging.getLogger(__name__)

ROLES = ['use', 'manage', 'owner']
ROLE_HIERARCHY = {'use': 1, 'manage': 2, 'owner': 3}
DEFAULT_ROLE = 'use'


def role_gte(a: str, b: str) -> bool:
    """Return True if role a >= role b in the privilege hierarchy."""
    return ROLE_HIERARCHY.get(a, 0) >= ROLE_HIERARCHY.get(b, 0)


async def is_workspace_admin(token: str, host: str) -> bool:
    """Check if the token owner is a Databricks workspace admin via SCIM /Me.
    Workspace admins belong to the built-in 'admins' group.
    """
    if not token or not host:
        return False
    if not host.startswith("http"):
        host = f"https://{host}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{host}/api/2.0/preview/scim/v2/Me",
                headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code == 200:
                groups = resp.json().get("groups", [])
                return any(g.get("display") == "admins" for g in groups)
    except Exception as e:
        logger.debug("Workspace admin check failed: %s", e)
    return False


async def resolve_role(identity: str, token: str, host: str) -> str:
    """
    Resolve the effective role for a user:
    1. Workspace admins → 'owner' (checked via Databricks SCIM API)
    2. Explicit assignment in user_roles table
    3. Default → 'use'
    """
    import app.services.database as _db

    # Workspace admins always get owner, regardless of any local assignment
    if await is_workspace_admin(token, host):
        return 'owner'

    # Check explicit assignment in the database
    if _db.db_service and identity:
        assigned = await _db.db_service.get_user_role(identity)
        if assigned:
            return assigned

    return DEFAULT_ROLE
