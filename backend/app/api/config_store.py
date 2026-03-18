"""
Shared server configuration overrides.
Both proxy_routes and genie_clone_routes read from here.
Updated via PUT /api/config.

Config is persisted to a JSON file for the lifetime of the app instance.
In Databricks Apps, this persists within a running deployment but not across
new deployments (fresh container = fresh /tmp). After a new deployment, the
user must re-save Settings once to repopulate the server config.
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

# Persist config to a file in the app's data directory
_CONFIG_FILE = Path(os.getenv("CONFIG_PERSIST_PATH", "/tmp/genie_cache_config.json"))


def _load_persisted_config():
    """Load config from disk on startup."""
    try:
        if _CONFIG_FILE.exists():
            data = json.loads(_CONFIG_FILE.read_text())
            _server_config_overrides.update(data)
            logger.info("Loaded persisted config from %s (%d keys)", _CONFIG_FILE, len(data))
    except Exception as e:
        logger.warning("Could not load persisted config: %s", e)


def _save_persisted_config():
    """Save current overrides to disk."""
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(json.dumps(_server_config_overrides))
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
    """Apply a batch of config overrides and persist to disk."""
    _server_config_overrides.update(updates)
    _save_persisted_config()


def get_overrides() -> dict:
    """Return current override dict (read-only copy)."""
    return dict(_server_config_overrides)
