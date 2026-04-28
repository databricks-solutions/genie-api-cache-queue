"""
Shared server configuration overrides.

Global settings are persisted to Lakebase (global_settings table) so they
survive redeploys. A small in-memory cache reflects the last known state
and is populated at startup via load_global_settings_from_db() and kept
in sync by update_overrides().

Sensitive keys (lakebase_service_token) are kept in memory only and never
written to Lakebase — the app always prefers the SP OAuth credentials
auto-injected into Databricks Apps (DATABRICKS_CLIENT_ID / _SECRET).
"""

import logging
import re
from typing import Any, Callable, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()

# In-memory snapshot of overrides (mirrors the Lakebase global_settings table).
_server_config_overrides: dict = {}

# Keys that stay in memory only — never persisted to Lakebase.
_NON_PERSISTED_KEYS = frozenset({"lakebase_service_token"})

# Tokens that mark a key as credential-bearing. Belt-and-suspenders in case
# a new secret-ish field is added to the pydantic settings models without also
# being listed in _NON_PERSISTED_KEYS. `_is_sensitive_key` is the single source
# of truth for "don't persist to Lakebase" — keep both the allowlist above and
# the token guard so a missed listing still short-circuits the DB write.
#
# Match at underscore-delimited boundaries (start/end of key or between `_`)
# so "pat" flags "databricks_pat" but not "patch_interval" / "path_prefix",
# and "key" does not false-positive on "sql_warehouse_id" etc.
_SENSITIVE_TOKENS = ("token", "secret", "pat", "password", "api_key")
_SENSITIVE_PATTERN = re.compile(
    r"(?:^|_)(?:" + "|".join(re.escape(s) for s in _SENSITIVE_TOKENS) + r")(?:$|_)"
)


def _is_sensitive_key(key: str) -> bool:
    """Return True if the key should be kept in memory only (never persisted)."""
    if key in _NON_PERSISTED_KEYS:
        return True
    return bool(_SENSITIVE_PATTERN.search(key.lower()))

# Keys whose empty-string value should clear the override (and the DB row)
# rather than persist as "". Covers the SP token (sensitive, memory-only) plus
# the three per-service LLM endpoint overrides: the gateway settings UI sends
# "" when the user picks the "Use default" option, and we want that to fall
# back to the module-level default instead of leaving `{"value": ""}` in
# Lakebase (which would silently pin the gateway to "no endpoint").
_CLEARABLE_KEYS = frozenset({
    "lakebase_service_token",
    "normalization_model",
    "validation_model",
    "intent_split_model",
})


def _coerce_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes", "on")
    return bool(v)


# Typed schema for persisted global settings. Values coming back from JSONB
# are coerced to the expected Python type on load so a future bad write (or a
# manual row edit) can't silently flow a string through `or` / numeric compares
# in downstream code. Unknown keys pass through untouched.
_SETTING_TYPES: dict[str, Callable[[Any], Any]] = {
    "similarity_threshold": float,
    "cache_ttl_hours": float,
    "max_queries_per_minute": int,
    "shared_cache": _coerce_bool,
    "question_normalization_enabled": _coerce_bool,
    "cache_validation_enabled": _coerce_bool,
    "intent_split_enabled": _coerce_bool,
    "caching_enabled": _coerce_bool,
    "embedding_provider": str,
    "databricks_embedding_endpoint": str,
    "normalization_model": str,
    "validation_model": str,
    "intent_split_model": str,
    "sql_warehouse_id": str,
    "lakebase_instance_name": str,
    "lakebase_catalog": str,
    "lakebase_schema": str,
    "cache_table_name": str,
    "query_log_table_name": str,
    "genie_space_id": str,
    "storage_backend": str,
}


def _coerce_persisted_settings(raw: dict) -> dict:
    """Coerce each known key to its declared type; pass unknown keys through."""
    coerced: dict = {}
    for k, v in raw.items():
        if v is None:
            coerced[k] = None
            continue
        caster = _SETTING_TYPES.get(k)
        if caster is None:
            coerced[k] = v
            continue
        try:
            coerced[k] = caster(v)
        except (TypeError, ValueError) as e:
            logger.warning(
                "Global settings: could not coerce %s=%r to %s (%s); keeping raw",
                k, v, caster.__name__, e,
            )
            coerced[k] = v
    return coerced


async def load_global_settings_from_db() -> None:
    """Hydrate the in-memory cache from the Lakebase global_settings table.

    Called once during FastAPI lifespan, after storage initialization and
    BEFORE uvicorn starts serving requests — which is what makes the
    clear-then-reload pattern below safe. If a future caller invokes this
    concurrently with `update_overrides`, the cache can briefly reflect only
    the DB snapshot (losing an in-flight write). That is acceptable for the
    lifespan hydrate path; do not call from a request handler.
    """
    try:
        import app.services.database as _db
        if _db.db_service is None:
            logger.warning("Global settings: storage not initialized, skipping DB hydrate")
            return
        persisted = await _db.db_service.get_global_settings()
    except Exception as e:
        logger.warning("Global settings: could not load from Lakebase (%s); using env defaults only", e)
        return

    # Keep non-persisted keys (e.g. session-scoped tokens) intact.
    for k in list(_server_config_overrides.keys()):
        if not _is_sensitive_key(k):
            _server_config_overrides.pop(k, None)
    _server_config_overrides.update(_coerce_persisted_settings(persisted))
    logger.info("Global settings loaded from Lakebase (%d keys)", len(persisted))


def get_effective_setting(key: str):
    """Return the effective value for a setting.

    Precedence: in-memory override (DB-backed) > app.config defaults (env vars).
    """
    if key in _server_config_overrides:
        return _server_config_overrides[key]
    return getattr(_settings, key, None)


async def update_overrides(updates: dict, updated_by: Optional[str] = None) -> None:
    """Apply a batch of setting overrides.

    Non-sensitive keys are upserted into the Lakebase `global_settings` table;
    sensitive keys (see `_NON_PERSISTED_KEYS`) are kept in memory only.

    The in-memory cache is updated only AFTER the DB write succeeds so the
    cache never diverges from the persisted state. Sensitive in-memory keys
    that bypass Lakebase are committed unconditionally (nothing to persist).
    """
    if not updates:
        return

    # Normalize: treat empty strings as a reset for clearable keys
    normalized: dict = {}
    clears: list[str] = []
    for k, v in updates.items():
        if k in _CLEARABLE_KEYS and v == "":
            clears.append(k)
        else:
            normalized[k] = v

    db_updates = {k: v for k, v in normalized.items() if not _is_sensitive_key(k)}
    mem_only_updates = {k: v for k, v in normalized.items() if _is_sensitive_key(k)}
    persisted_clears = [k for k in clears if not _is_sensitive_key(k)]
    mem_only_clears = [k for k in clears if _is_sensitive_key(k)]

    # Persist to Lakebase first; only touch the in-memory snapshot for keys whose
    # DB write actually succeeded, so a failed DB op can't leave the cache ahead
    # of the persisted state (which would "reappear" on restart and confuse the
    # user). Delete failures downgrade to per-key skips rather than aborting the
    # whole batch — the successful upserts already cost a DB round-trip.
    cache_applies: dict = dict(db_updates)
    cache_clears: list[str] = list(mem_only_clears)
    if db_updates or persisted_clears:
        import app.services.database as _db
        if _db.db_service is None:
            logger.warning(
                "Global settings: storage not initialized, skipping DB persist for %s",
                list(db_updates.keys()) + persisted_clears,
            )
            # No DB to write to — don't touch the cache for would-be persisted
            # keys either, so get_effective_setting keeps returning the old
            # value (consistent with "DB is source of truth").
            cache_applies = {}
        else:
            if db_updates:
                try:
                    await _db.db_service.update_global_settings(db_updates, updated_by)
                except Exception:
                    # Upsert failed — don't apply *any* of this batch to the cache.
                    # executemany is inside a transaction so the DB state is
                    # unchanged; mirroring that here keeps the invariant.
                    logger.exception("Global settings: upsert failed for %s", list(db_updates.keys()))
                    raise
            for k in persisted_clears:
                try:
                    await _db.db_service.delete_global_setting(k)
                    cache_clears.append(k)
                except Exception as e:
                    # Per-key skip: leave the cache value untouched so the next
                    # read returns the same thing as a cold reload from the DB.
                    # The already-committed db_updates stay applied in cache.
                    logger.warning(
                        "Global settings: delete of %s failed (%s); leaving cache value intact",
                        k, e,
                    )

    # DB is consistent — apply only the ops whose DB side actually succeeded.
    for k in cache_clears:
        _server_config_overrides.pop(k, None)
    if cache_applies:
        _server_config_overrides.update(cache_applies)
    if mem_only_updates:
        _server_config_overrides.update(mem_only_updates)


def invalidate_key(key: str) -> None:
    """Remove a key from the in-memory override snapshot.

    Use this from route handlers that delete a persisted setting directly
    (e.g. DELETE /settings/{key}) so the in-process cache doesn't keep serving
    a stale value until the next restart.
    """
    _server_config_overrides.pop(key, None)


async def delete_override(key: str) -> bool:
    """Delete a persisted override.

    Ordering: DB delete runs first; the in-memory cache is only invalidated
    AFTER a successful DB delete. This preserves the invariant that the cache
    never holds a value that the DB does not also hold — on DB failure, both
    keep the old value; on success, a tiny read-window may see the cached
    value before invalidation, which is preferable to the opposite case
    (cache cleared but DB delete failed, causing the key to reappear on
    restart and confuse the user).

    Sensitive (non-persisted) keys are a pure cache-only operation.
    """
    if _is_sensitive_key(key):
        existed = key in _server_config_overrides
        _server_config_overrides.pop(key, None)
        return existed

    import app.services.database as _db
    if _db.db_service is None:
        logger.warning("Global settings: storage not initialized, cannot delete %s", key)
        return False

    deleted = await _db.db_service.delete_global_setting(key)
    _server_config_overrides.pop(key, None)
    return deleted


def get_overrides() -> dict:
    """Return a read-only copy of the current in-memory override snapshot."""
    return dict(_server_config_overrides)
