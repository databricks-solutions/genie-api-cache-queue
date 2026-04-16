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
import re
import time

import httpx

from app.auth import ensure_https

_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+$')

logger = logging.getLogger(__name__)


def _get_sp_token() -> str:
    """Get the app's service principal token for SCIM calls."""
    from app.auth import get_service_principal_token
    return get_service_principal_token() or ""

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
_ADMIN_CACHE_MAX = 500
_ROLE_CACHE_MAX = 500
_admin_cache: dict[str, tuple[bool, float]] = {}   # token → (is_admin, expires_at)
_role_cache: dict[str, tuple[str, float]] = {}     # identity → (role, expires_at)

_GROUP_CACHE_TTL = 60.0
_GROUP_CACHE_MAX = 500
_group_cache: dict[str, tuple[list[str], float]] = {}


def _sweep_expired_group_cache():
    now = time.monotonic()
    expired = [k for k, (_, exp) in _group_cache.items() if now >= exp]
    for k in expired:
        del _group_cache[k]
    if len(_group_cache) > _GROUP_CACHE_MAX:
        by_expiry = sorted(_group_cache.items(), key=lambda kv: kv[1][1])
        for k, _ in by_expiry[:len(_group_cache) - _GROUP_CACHE_MAX]:
            del _group_cache[k]


async def close_http_client():
    """Close the shared HTTP client. Call during app shutdown."""
    await _http_client.aclose()


def _sweep_expired_admin_cache():
    """Remove expired entries, then evict oldest if still over max."""
    now = time.monotonic()
    expired = [k for k, (_, exp) in _admin_cache.items() if now >= exp]
    for k in expired:
        del _admin_cache[k]
    if len(_admin_cache) > _ADMIN_CACHE_MAX:
        by_expiry = sorted(_admin_cache.items(), key=lambda kv: kv[1][1])
        for k, _ in by_expiry[:len(_admin_cache) - _ADMIN_CACHE_MAX]:
            del _admin_cache[k]


def _sweep_expired_role_cache():
    """Remove expired entries, then evict oldest if still over max."""
    now = time.monotonic()
    expired = [k for k, (_, exp) in _role_cache.items() if now >= exp]
    for k in expired:
        del _role_cache[k]
    if len(_role_cache) > _ROLE_CACHE_MAX:
        by_expiry = sorted(_role_cache.items(), key=lambda kv: kv[1][1])
        for k, _ in by_expiry[:len(_role_cache) - _ROLE_CACHE_MAX]:
            del _role_cache[k]


def role_gte(a: str, b: str) -> bool:
    """Return True if role a >= role b in the privilege hierarchy."""
    return ROLE_HIERARCHY.get(a, 0) >= ROLE_HIERARCHY.get(b, 0)


def invalidate_role_cache(identity: str) -> None:
    """Evict a cached role so the next request re-reads from the database.
    Call this immediately after any set_user_role / delete_user_role write.
    """
    _role_cache.pop(identity, None)


def invalidate_group_cache():
    """Clear group-related caches after group role changes."""
    _group_cache.clear()
    _role_cache.clear()


async def is_workspace_admin(token: str, host: str, identity: str = "") -> bool:
    """Check if a user is a Databricks workspace admin via SCIM.

    When token is provided, calls /Me with the user's token.
    When token is empty and identity is provided, uses the SP token to look
    up the user by email via /Users.
    Result is cached for _ADMIN_CACHE_TTL seconds to avoid per-request SCIM calls.
    """
    cache_key = token or identity
    if not cache_key or not host:
        return False
    host = ensure_https(host)

    now = time.monotonic()
    if len(_admin_cache) > _ADMIN_CACHE_MAX:
        _sweep_expired_admin_cache()

    cached = _admin_cache.get(cache_key)
    if cached is not None:
        result, expires_at = cached
        if now < expires_at:
            return result

    result = False
    try:
        if token:
            resp = await _http_client.get(
                f"{host}/api/2.0/preview/scim/v2/Me",
                headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code == 200:
                groups = resp.json().get("groups", [])
                result = any(g.get("display") == "admins" for g in groups)
        elif identity:
            sp_token = _get_sp_token()
            if sp_token:
                resp = await _http_client.get(
                    f"{host}/api/2.0/preview/scim/v2/Users",
                    headers={"Authorization": f"Bearer {sp_token}"},
                    params={"filter": f'userName eq "{identity}"', "attributes": "groups"},
                )
                if resp.status_code == 200:
                    resources = resp.json().get("Resources", [])
                    if resources:
                        groups = resources[0].get("groups", [])
                        result = any(g.get("display") == "admins" for g in groups)
    except Exception as e:
        logger.warning("Workspace admin check failed: %s", e)

    _admin_cache[cache_key] = (result, now + _ADMIN_CACHE_TTL)
    return result


async def is_user_workspace_admin(email: str, caller_token: str, host: str) -> bool:
    """Check if a specific user (by email) is a workspace admin via SCIM Users API.

    Unlike is_workspace_admin (which checks the token owner via /Me), this
    looks up an arbitrary user by email.  Uses the caller's token for the
    SCIM request — the caller must have permission to read user records.
    """
    if not email or not caller_token or not host:
        return False
    if not _EMAIL_RE.match(email):
        return False
    host = ensure_https(host)
    try:
        resp = await _http_client.get(
            f"{host}/api/2.0/preview/scim/v2/Users",
            headers={"Authorization": f"Bearer {caller_token}"},
            params={"filter": f'userName eq "{email}"', "attributes": "groups"},
        )
        if resp.status_code == 200:
            resources = resp.json().get("Resources", [])
            if resources:
                groups = resources[0].get("groups", [])
                return any(g.get("display") == "admins" for g in groups)
    except Exception as e:
        logger.warning("User workspace admin check failed for %s: %s", email, e)
    return False


async def get_user_groups(email: str, host: str) -> list[str]:
    """Return display names of groups the user belongs to via SCIM.
    Uses the SP token to avoid OBO scope limitations.
    """
    if not email or not host:
        return []
    if not _EMAIL_RE.match(email):
        return []

    now = time.monotonic()
    if len(_group_cache) > _GROUP_CACHE_MAX:
        _sweep_expired_group_cache()

    cached = _group_cache.get(email)
    if cached is not None:
        groups, expires_at = cached
        if now < expires_at:
            return groups

    host = ensure_https(host)
    token = _get_sp_token()
    if not token:
        return []

    groups = []
    try:
        resp = await _http_client.get(
            f"{host}/api/2.0/preview/scim/v2/Users",
            headers={"Authorization": f"Bearer {token}"},
            params={"filter": f'userName eq "{email}"', "attributes": "groups"},
        )
        if resp.status_code == 200:
            resources = resp.json().get("Resources", [])
            if resources:
                groups = [
                    g.get("display", "")
                    for g in resources[0].get("groups", [])
                    if g.get("display")
                ]
    except Exception as e:
        logger.warning("Failed to fetch groups for %s: %s", email, e)

    _group_cache[email] = (groups, now + _GROUP_CACHE_TTL)
    return groups


_ws_groups_cache: tuple[list[dict], float] | None = None
_WS_GROUPS_CACHE_TTL = 300.0


async def list_workspace_groups(host: str) -> list[dict]:
    """List all workspace groups via SCIM using the SP token. Cached 5 min."""
    global _ws_groups_cache
    now = time.monotonic()
    if _ws_groups_cache is not None:
        cached_groups, expires_at = _ws_groups_cache
        if now < expires_at:
            return cached_groups

    token = _get_sp_token()
    if not token or not host:
        return []
    host = ensure_https(host)

    all_groups = []
    start_index = 1
    page_size = 500
    try:
        while True:
            resp = await _http_client.get(
                f"{host}/api/2.0/preview/scim/v2/Groups",
                headers={"Authorization": f"Bearer {token}"},
                params={"count": page_size, "startIndex": start_index, "attributes": "displayName"},
            )
            if resp.status_code != 200:
                logger.warning("SCIM Groups API returned %d", resp.status_code)
                break
            data = resp.json()
            resources = data.get("Resources", [])
            for g in resources:
                name = g.get("displayName", "")
                if name:
                    all_groups.append({"displayName": name})
            total = data.get("totalResults", 0)
            if start_index + page_size > total or not resources:
                break
            start_index += page_size
    except Exception as e:
        logger.warning("Failed to list workspace groups: %s", e)

    _ws_groups_cache = (all_groups, now + _WS_GROUPS_CACHE_TTL)
    return all_groups


async def resolve_role(identity: str, token: str, host: str) -> str:
    """
    Resolve the effective role for a user:
    1. Workspace admins → 'owner' (checked via Databricks SCIM API, cached 60 s)
    2. Explicit assignment in user_roles table (cached 120 s, invalidated on write)
    3. Highest group role from group_roles table
    4. Default → 'use'
    """
    import app.services.database as _db

    if await is_workspace_admin(token, host, identity=identity):
        return 'owner'

    if not identity:
        return DEFAULT_ROLE

    now = time.monotonic()
    cached = _role_cache.get(identity)
    if cached is not None:
        role, expires_at = cached
        if now < expires_at:
            return role

    # 1. Explicit user role
    assigned = None
    if _db.db_service:
        assigned = await _db.db_service.get_user_role(identity)

    if assigned:
        role = assigned
    else:
        # 2. Highest group role
        role = DEFAULT_ROLE
        if _db.db_service:
            user_groups = await get_user_groups(identity, host)
            if user_groups:
                for g in user_groups:
                    g_role = await _db.db_service.get_group_role(g)
                    if g_role and ROLE_HIERARCHY.get(g_role, 0) > ROLE_HIERARCHY.get(role, 0):
                        role = g_role

    if len(_role_cache) > _ROLE_CACHE_MAX:
        _sweep_expired_role_cache()
    _role_cache[identity] = (role, now + _ROLE_CACHE_TTL)
    return role
