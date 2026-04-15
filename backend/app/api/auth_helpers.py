"""
Shared authentication helpers for API routes.
"""

import logging
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


def extract_bearer_token(request: Request) -> str:
    """Extract user auth token from request headers.
    In Databricks Apps: always X-Forwarded-Access-Token.
    For direct API access: Authorization: Bearer header.
    """
    forwarded = request.headers.get("X-Forwarded-Access-Token", "").strip()
    if forwarded:
        return forwarded

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        if token:
            return token

    raise HTTPException(
        status_code=401,
        detail="Missing authentication. Provide X-Forwarded-Access-Token or Authorization: Bearer <token>.",
    )


def extract_bearer_token_optional(request: Request) -> str:
    """Like extract_bearer_token, but returns empty string instead of raising 401."""
    forwarded = request.headers.get("X-Forwarded-Access-Token", "").strip()
    if forwarded:
        return forwarded
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        if token:
            return token
    return ""


def resolve_user_token(request: Request) -> str:
    """Resolve the best available user token for API calls.

    Priority:
      1. X-Forwarded-Access-Token (user token passthrough enabled)
      2. Authorization: Bearer header (external API clients)
      3. App's service principal token (fallback when passthrough disabled)

    Raises 401 only when no token source is available at all.
    """
    token = extract_bearer_token_optional(request)
    if token:
        return token

    from app.auth import get_service_principal_token
    sp_token = get_service_principal_token()
    if sp_token:
        logger.warning("Using service principal token — user token passthrough is disabled.")
        return sp_token

    raise HTTPException(
        status_code=401,
        detail="No authentication token available. Enable user token passthrough or configure a service principal.",
    )


def resolve_user_token_optional(request: Request) -> str:
    """Like resolve_user_token, but returns empty string instead of raising 401."""
    try:
        return resolve_user_token(request)
    except HTTPException:
        return ""


def build_simple_runtime_settings(token: str):
    """Build RuntimeSettings for management endpoints that only need a user token."""
    from app.models import RuntimeConfig
    from app.runtime_config import RuntimeSettings
    rc = RuntimeConfig()
    return RuntimeSettings(rc, token, None)


async def require_role(req: Request, min_role: str) -> tuple:
    """Resolve caller's effective role and raise 403 if below min_role.

    Returns (identity, token, role).  When user token passthrough is
    disabled, falls back to email-only identity (SCIM admin check is
    skipped, DB role lookup still works).
    """
    from app.api.config_store import get_effective_setting
    from app.auth import ensure_https
    from app.config import get_settings
    from app.services.rbac import resolve_role, role_gte

    identity = req.headers.get("X-Forwarded-Email", "")
    token = extract_bearer_token_optional(req)

    if not token and not identity:
        raise HTTPException(
            status_code=401,
            detail="No authentication token or user identity available.",
        )
    if not token and identity:
        logger.info("Email-only identity for %s (no bearer token) — default role only", identity)
        role = "use"
        if not role_gte(role, min_role):
            raise HTTPException(
                status_code=403,
                detail=f"Role '{min_role}' required. Without a bearer token, only the default 'use' role is granted.",
            )
        return identity, token, role

    _s = get_settings()
    host = get_effective_setting("databricks_host") or _s.databricks_host or ""
    host = ensure_https(host) if host else ""

    role = await resolve_role(identity, token, host)
    if not role_gte(role, min_role):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{min_role}' required. You have '{role}'.",
        )
    return identity, token, role


def ttl_hours_to_seconds(hours: float) -> int:
    return int(hours * 3600)


def ttl_seconds_to_hours(seconds: int) -> float:
    return seconds / 3600
