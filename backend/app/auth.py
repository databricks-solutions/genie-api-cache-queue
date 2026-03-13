"""
Authentication helper for Databricks API calls.
Handles both Service Principal and User Auth tokens using Databricks SDK.
"""

import logging
import os
from typing import Optional
from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)

_sp_workspace_client: Optional[WorkspaceClient] = None


def get_service_principal_client() -> Optional[WorkspaceClient]:
    """Get WorkspaceClient authenticated with Service Principal."""
    global _sp_workspace_client

    if _sp_workspace_client:
        return _sp_workspace_client

    client_id = os.getenv("DATABRICKS_CLIENT_ID")
    client_secret = os.getenv("DATABRICKS_CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.warning("DATABRICKS_CLIENT_ID or DATABRICKS_CLIENT_SECRET not set")
        return None

    try:
        _sp_workspace_client = WorkspaceClient()
        logger.info("Service Principal WorkspaceClient initialized")
        return _sp_workspace_client
    except Exception as e:
        logger.error("Failed to create Service Principal client: %s", e)
        return None


def get_service_principal_token() -> Optional[str]:
    """Get OAuth2 token for Service Principal using Databricks SDK."""
    client = get_service_principal_client()
    if not client:
        token = os.getenv("DATABRICKS_TOKEN", "")
        if token:
            logger.debug("Using DATABRICKS_TOKEN from environment (local dev)")
        return token

    try:
        if hasattr(client.config, '_header_factory') and callable(client.config._header_factory):
            auth_headers = client.config._header_factory()
            if isinstance(auth_headers, dict) and 'Authorization' in auth_headers:
                auth_value = auth_headers['Authorization']
                if auth_value.startswith('Bearer '):
                    return auth_value[7:]
                return auth_value

        if hasattr(client.config, '_credentials_strategy'):
            creds = client.config._credentials_strategy
            if hasattr(creds, 'token') and callable(creds.token):
                token = creds.token(client.config)
                if token:
                    return token

        logger.warning("Could not extract token from SDK, falling back to env var")
        return os.getenv("DATABRICKS_TOKEN", "")

    except Exception:
        logger.exception("Failed to get token from SDK")
        return os.getenv("DATABRICKS_TOKEN", "")


def ensure_https(host: str) -> str:
    """Ensure host has https:// protocol."""
    if not host:
        return ""
    if not host.startswith(('http://', 'https://')):
        return f"https://{host}"
    return host
