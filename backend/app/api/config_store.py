"""
Shared server configuration overrides.
Both proxy_routes and genie_clone_routes read from here.
Updated via PUT /api/config.

Config is persisted to /tmp for the lifetime of the running container.
Credentials (lakebase_service_token) are NOT stored here — they come from:
  - DATABRICKS_TOKEN env var (auto-injected by Databricks Apps, used for Lakebase)
  - Databricks Secrets referenced in app.yaml (for production credential management)
"""

import json
import logging
import os
from pathlib import Path
from app.config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()

# In-memory overrides
_server_config_overrides: dict = {}

# Non-sensitive config persisted to /tmp (survives within a running instance)
_CONFIG_FILE = Path(os.getenv("CONFIG_PERSIST_PATH", "/tmp/genie_cache_config.json"))


def _load_persisted_config():
    """Load non-sensitive config from /tmp on startup."""
    try:
        if _CONFIG_FILE.exists():
            data = json.loads(_CONFIG_FILE.read_text())
            _server_config_overrides.update(data)
            logger.info("Loaded persisted config from %s (%d keys)", _CONFIG_FILE, len(data))
    except Exception as e:
        logger.warning("Could not load persisted config: %s", e)


def _save_persisted_config():
    """Persist non-sensitive config to /tmp."""
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Never write credentials to disk
        safe = {k: v for k, v in _server_config_overrides.items() if 'token' not in k and 'secret' not in k and 'pat' not in k}
        _CONFIG_FILE.write_text(json.dumps(safe))
    except Exception as e:
        logger.warning("Could not persist config: %s", e)


# Load on import
_load_persisted_config()


def get_effective_setting(key: str):
    """Get setting value: override > env/settings default."""
    if key in _server_config_overrides:
        return _server_config_overrides[key]
    return getattr(_settings, key, None)


def update_overrides(updates: dict):
    """Apply a batch of config overrides. Credentials are kept in memory only (not written to disk)."""
    _server_config_overrides.update(updates)
    _save_persisted_config()


def get_overrides() -> dict:
    """Return current override dict (read-only copy)."""
    return dict(_server_config_overrides)
