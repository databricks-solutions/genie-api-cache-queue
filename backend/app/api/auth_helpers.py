"""
Shared authentication and conversion helpers for API routes.
"""

import logging
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


def extract_bearer_token(request: Request) -> str:
    """Extract auth token from request headers.

    Priority:
    1. X-Forwarded-Access-Token (Databricks Apps proxy)
    2. Authorization: Bearer header (direct API access)
    3. App SP token (Databricks Apps without user auth resource)
    """
    forwarded = request.headers.get("X-Forwarded-Access-Token", "").strip()
    if forwarded:
        return forwarded

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        if token:
            return token

    if request.headers.get("X-Forwarded-Email"):
        from app.auth import get_service_principal_token
        sp_token = get_service_principal_token()
        if sp_token:
            logger.info("Using app SP token for authenticated user %s",
                        request.headers.get("X-Forwarded-Email"))
            return sp_token

    raise HTTPException(
        status_code=401,
        detail="Missing authentication. Provide Authorization: Bearer <token> or access via Databricks Apps.",
    )


def build_simple_runtime_settings(token: str):
    """Build RuntimeSettings for management endpoints that only need a token."""
    from app.models import RuntimeConfig
    from app.runtime_config import RuntimeSettings
    rc = RuntimeConfig(auth_mode="user", user_pat=token)
    return RuntimeSettings(rc, None, None)


def ttl_hours_to_seconds(hours: float) -> int:
    """Convert TTL from hours (internal) to seconds (API)."""
    return int(hours * 3600)


def ttl_seconds_to_hours(seconds: int) -> float:
    """Convert TTL from seconds (API) to hours (internal)."""
    return seconds / 3600
