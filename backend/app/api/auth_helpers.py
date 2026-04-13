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
