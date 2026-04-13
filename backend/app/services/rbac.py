"""
Role-based access control for Genie Cache Gateway.

Roles (lowest → highest privilege):
  use     — query only: submit questions, view results
  manage  — configure gateways, view/clear cache, manage users
  owner   — full control: create/delete gateways, configure settings

Workspace admins are always treated as owner regardless of the user_roles table.
Unassigned users default to 'use'.
"""

import logging
import time

import httpx

from app.auth import ensure_https

logger = logging.getLogger(__name__)

ROLES = ['use', 'manage', 'owner']
ROLE_HIERARCHY = {'use': 1, 'manage': 2, 'owner': 3}
DEFAULT_ROLE = 'use'

# Shared HTTP client — avoids per-call TCP+TLS handshake overhead
_http_client = httpx.AsyncClient(timeout=5.0)

# Short-lived in-process caches to avoid hammering SCIM and DB on every request.
# Keys: token (admin check) and identity (role lookup). TTLs are conservative —
# role changes take effect within the TTL window without a restart.
_ADMIN_CACHE_TTL = 60.0   # seconds
_ROLE_CACHE_TTL = 120.0   # seconds
_admin_cache: dict[str, tuple[bool, float]] = {}   # token → (is_admin, expires_at)
_role_cache: dict[str, tuple[str, float]] = {}     # identity → (role, expires_at)


def role_gte(a: str, b: str) -> bool:
    """Return True if role a >= role b in the privilege hierarchy."""
    return ROLE_HIERARCHY.get(a, 0) >= ROLE_HIERARCHY.get(b, 0)


def invalidate_role_cache(identity: str) -> None:
    """Evict a cached role so the next request re-reads from the database.
    Call this immediately after any set_user_role / delete_user_role write.
    """
    _role_cache.pop(identity, None)


async def is_workspace_admin(token: str, host: str) -> bool:
    """Check if the token owner is a Databricks workspace admin via SCIM /Me.
    Result is cached for _ADMIN_CACHE_TTL seconds to avoid per-request SCIM calls.
    """
    if not token or not host:
        return False
    host = ensure_https(host)

    now = time.monotonic()
    cached = _admin_cache.get(token)
    if cached is not None:
        result, expires_at = cached
        if now < expires_at:
            return result

    result = False
    try:
        resp = await _http_client.get(
            f"{host}/api/2.0/preview/scim/v2/Me",
            headers={"Authorization": f"Bearer {token}"}
        )
        if resp.status_code == 200:
            groups = resp.json().get("groups", [])
            result = any(g.get("display") == "admins" for g in groups)
    except Exception as e:
        logger.debug("Workspace admin check failed: %s", e)

    _admin_cache[token] = (result, now + _ADMIN_CACHE_TTL)
    return result


async def bootstrap_admin_if_needed() -> None:
    """Auto-assign 'owner' to BOOTSTRAP_ADMIN_EMAIL if no users exist in the DB.

    This is the recommended way to seed the first admin when user token
    passthrough is disabled — SCIM auto-detection cannot work without the
    user's own OAuth token.
    """
    import app.services.database as _db
    from app.config import get_settings

    email = get_settings().bootstrap_admin_email
    if not email or not _db.db_service:
        return

    try:
        existing = await _db.db_service.list_user_roles()
        if existing:
            logger.debug("Bootstrap skipped — %d user(s) already in DB", len(existing))
            return

        await _db.db_service.set_user_role(email, "owner", granted_by="bootstrap")
        logger.info("Bootstrap: assigned 'owner' role to %s", email)
    except Exception as e:
        logger.error("Bootstrap admin failed: %s", e)


async def resolve_role(identity: str, token: str, host: str) -> str:
    """
    Resolve the effective role for a user:
    1. Workspace admins → 'owner' (checked via Databricks SCIM API, cached 60 s)
    2. Explicit assignment in user_roles table (cached 120 s, invalidated on write)
    3. Default → 'use'
    """
    import app.services.database as _db

    if await is_workspace_admin(token, host):
        return 'owner'

    now = time.monotonic()
    cached = _role_cache.get(identity)
    if cached is not None:
        role, expires_at = cached
        if now < expires_at:
            return role

    assigned = None
    if _db.db_service and identity:
        assigned = await _db.db_service.get_user_role(identity)

    role = assigned or DEFAULT_ROLE
    _role_cache[identity] = (role, now + _ROLE_CACHE_TTL)
    return role
