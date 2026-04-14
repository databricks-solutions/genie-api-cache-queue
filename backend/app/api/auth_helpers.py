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
    Raises 401 if no token is found.
    """
    token = extract_bearer_token_optional(request)
    if token:
        return token

    raise HTTPException(
        status_code=401,
        detail="Missing authentication. Provide X-Forwarded-Access-Token or Authorization: Bearer <token>.",
    )


def extract_bearer_token_optional(request: Request) -> str:
    """Extract user auth token if available, return empty string otherwise.
    Use this when the caller can degrade gracefully without a token
    (e.g. when user token passthrough is disabled in Databricks Apps).
    """
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
    """Resolve a token for Genie/SQL API calls.

    Priority:
      1. X-Forwarded-Access-Token (user token passthrough enabled)
      2. Authorization: Bearer header (external API clients)
      3. App's service principal token (fallback when passthrough disabled)

    When falling back to SP, per-user access controls and lineage are NOT
    enforced.  The SP must have access to the target Genie Spaces and
    SQL Warehouses.
    """
    token = extract_bearer_token_optional(request)
    if token:
        return token

    # Fallback: use the app's SP token
    from app.auth import get_service_principal_token
    sp_token = get_service_principal_token()
    if sp_token:
        logger.warning(
            "No user token available — falling back to service principal. "
            "Per-user access controls and data lineage are NOT enforced."
        )
        return sp_token

    raise HTTPException(
        status_code=401,
        detail="No user token (passthrough disabled) and no service principal token available.",
    )


def resolve_user_token_optional(request: Request) -> str:
    """Same as resolve_user_token but returns empty string instead of raising."""
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


def ttl_hours_to_seconds(hours: float) -> int:
    return int(hours * 3600)


def ttl_seconds_to_hours(seconds: int) -> float:
    return seconds / 3600
