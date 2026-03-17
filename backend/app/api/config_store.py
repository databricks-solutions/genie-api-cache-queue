"""
Shared server configuration overrides.
Both proxy_routes and genie_clone_routes read from here.
Updated via PUT /api/v1/config.
"""

from app.config import get_settings

_settings = get_settings()

# In-memory overrides (persists for app lifetime, lost on restart)
_server_config_overrides: dict = {}


def get_effective_setting(key: str):
    """Get setting value: override > env/settings default."""
    if key in _server_config_overrides:
        return _server_config_overrides[key]
    return getattr(_settings, key, None)


def update_overrides(updates: dict):
    """Apply a batch of config overrides."""
    _server_config_overrides.update(updates)


def get_overrides() -> dict:
    """Return current override dict (read-only copy)."""
    return dict(_server_config_overrides)
