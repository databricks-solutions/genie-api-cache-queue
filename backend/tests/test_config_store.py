"""
Tests for app.api.config_store.

Regression coverage for issue #26:
- _coerce_persisted_settings guards against JSONB type drift so downstream
  numeric / boolean comparisons never receive a string sentinel.
- delete_override enforces DB-first ordering: cache is invalidated only
  AFTER a successful DB delete so a DB failure can't leave the cache in a
  falsely-empty state.
"""
import asyncio
import importlib
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


def _run(coro):
    """Run an async coroutine in a fresh event loop. Avoids the pytest-asyncio dep."""
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture
def config_store(monkeypatch):
    """Import app.api.config_store fresh against a stubbed app.config.

    conftest.py ships a lightweight stub of app.api.config_store; we replace
    it with the real module here and put back any required sibling stubs.
    """
    # app.config.get_settings provides the base defaults the module reads at
    # import time for `_settings`. The real object just needs the attributes
    # `get_effective_setting` returns as a fallback.
    base = types.SimpleNamespace(
        similarity_threshold=0.92,
        max_queries_per_minute=5,
        cache_ttl_hours=24.0,
    )
    config_stub = types.ModuleType("app.config")
    config_stub.get_settings = MagicMock(return_value=base)
    sys.modules["app.config"] = config_stub

    # Drop the conftest-registered stub so importlib loads the real module.
    sys.modules.pop("app.api.config_store", None)
    module = importlib.import_module("app.api.config_store")
    # Ensure app.api exposes the real module as attribute (for patch() paths).
    sys.modules["app.api"].config_store = module

    # Reset the in-memory override dict between tests
    module._server_config_overrides.clear()
    yield module

    # Cleanup: restore the conftest stub so other tests keep working
    sys.modules.pop("app.api.config_store", None)


class TestCoercePersistedSettings:
    """JSONB can hold any shape. Guard downstream code from type drift."""

    def test_float_from_string(self, config_store):
        out = config_store._coerce_persisted_settings({"similarity_threshold": "0.85"})
        assert out["similarity_threshold"] == 0.85
        assert isinstance(out["similarity_threshold"], float)

    def test_int_from_string(self, config_store):
        out = config_store._coerce_persisted_settings({"max_queries_per_minute": "42"})
        assert out["max_queries_per_minute"] == 42
        assert isinstance(out["max_queries_per_minute"], int)

    def test_bool_from_string_true(self, config_store):
        for s in ("true", "True", "1", "yes", "on"):
            out = config_store._coerce_persisted_settings({"shared_cache": s})
            assert out["shared_cache"] is True, f"{s!r} should coerce to True"

    def test_bool_from_string_false(self, config_store):
        for s in ("false", "0", "no", "off", ""):
            out = config_store._coerce_persisted_settings({"shared_cache": s})
            assert out["shared_cache"] is False, f"{s!r} should coerce to False"

    def test_bool_passthrough(self, config_store):
        out = config_store._coerce_persisted_settings({"shared_cache": True})
        assert out["shared_cache"] is True

    def test_none_passes_through(self, config_store):
        out = config_store._coerce_persisted_settings({"similarity_threshold": None})
        assert out["similarity_threshold"] is None

    def test_unknown_key_passes_through(self, config_store):
        out = config_store._coerce_persisted_settings({"future_key": {"nested": "value"}})
        assert out["future_key"] == {"nested": "value"}

    def test_uncoercible_value_kept_raw(self, config_store):
        """A bad write is logged but kept — we can't recover the original intent."""
        out = config_store._coerce_persisted_settings({"max_queries_per_minute": "not-a-number"})
        # Falls through, raw value retained (downstream may still error, but
        # that's more useful than silently returning 0)
        assert out["max_queries_per_minute"] == "not-a-number"


class TestGetEffectiveSetting:
    def test_override_wins_over_env(self, config_store):
        config_store._server_config_overrides["similarity_threshold"] = 0.5
        assert config_store.get_effective_setting("similarity_threshold") == 0.5

    def test_env_fallback_when_no_override(self, config_store):
        # No override — falls through to get_settings() attributes
        assert config_store.get_effective_setting("similarity_threshold") == 0.92

    def test_missing_key_returns_none(self, config_store):
        assert config_store.get_effective_setting("nonexistent_key") is None


class TestDeleteOverrideOrdering:
    """Cache is only cleared AFTER a successful DB delete. DB failure must
    leave the cache untouched so the user sees a consistent state on retry."""

    def test_successful_delete_clears_cache(self, config_store, monkeypatch):
        config_store._server_config_overrides["similarity_threshold"] = 0.5
        fake_service = MagicMock()
        fake_service.delete_global_setting = AsyncMock(return_value=True)
        # Patch db_service on the real (conftest-stubbed) module so the
        # `import app.services.database as _db` inside config_store picks it up
        # (import binds to whatever sys.modules returns, but parent-attribute
        # lookup also reads `app.services.database`).
        monkeypatch.setattr(sys.modules["app.services.database"], "db_service", fake_service, raising=False)

        deleted = _run(config_store.delete_override("similarity_threshold"))

        assert deleted is True
        assert "similarity_threshold" not in config_store._server_config_overrides
        fake_service.delete_global_setting.assert_awaited_once_with("similarity_threshold")

    def test_db_failure_leaves_cache_unchanged(self, config_store, monkeypatch):
        """If DB delete raises, the cached value must NOT be removed — otherwise
        a retry would see the cache empty but the DB still holding the value,
        which causes the key to 'reappear' on restart."""
        config_store._server_config_overrides["similarity_threshold"] = 0.5
        fake_service = MagicMock()
        fake_service.delete_global_setting = AsyncMock(side_effect=RuntimeError("DB down"))
        # Patch db_service on the real (conftest-stubbed) module so the
        # `import app.services.database as _db` inside config_store picks it up
        # (import binds to whatever sys.modules returns, but parent-attribute
        # lookup also reads `app.services.database`).
        monkeypatch.setattr(sys.modules["app.services.database"], "db_service", fake_service, raising=False)

        with pytest.raises(RuntimeError, match="DB down"):
            _run(config_store.delete_override("similarity_threshold"))

        assert config_store._server_config_overrides.get("similarity_threshold") == 0.5

    def test_non_persisted_key_is_cache_only(self, config_store, monkeypatch):
        """Sensitive keys (lakebase_service_token) never touch the DB."""
        config_store._server_config_overrides["lakebase_service_token"] = "secret"
        fake_service = MagicMock()
        fake_service.delete_global_setting = AsyncMock(return_value=True)
        # Patch db_service on the real (conftest-stubbed) module so the
        # `import app.services.database as _db` inside config_store picks it up
        # (import binds to whatever sys.modules returns, but parent-attribute
        # lookup also reads `app.services.database`).
        monkeypatch.setattr(sys.modules["app.services.database"], "db_service", fake_service, raising=False)

        deleted = _run(config_store.delete_override("lakebase_service_token"))

        assert deleted is True
        assert "lakebase_service_token" not in config_store._server_config_overrides
        fake_service.delete_global_setting.assert_not_awaited()


class TestUpdateOverridesOrdering:
    """DB write happens first; cache is only updated after success so a
    failed DB write can't leave the cache holding a value that will be lost
    on restart."""

    def test_successful_update_writes_to_cache(self, config_store, monkeypatch):
        fake_service = MagicMock()
        fake_service.update_global_settings = AsyncMock(return_value=None)
        # Patch db_service on the real (conftest-stubbed) module so the
        # `import app.services.database as _db` inside config_store picks it up
        # (import binds to whatever sys.modules returns, but parent-attribute
        # lookup also reads `app.services.database`).
        monkeypatch.setattr(sys.modules["app.services.database"], "db_service", fake_service, raising=False)

        _run(config_store.update_overrides({"similarity_threshold": 0.8}))

        assert config_store._server_config_overrides["similarity_threshold"] == 0.8
        fake_service.update_global_settings.assert_awaited_once()

    def test_db_failure_leaves_cache_unchanged(self, config_store, monkeypatch):
        fake_service = MagicMock()
        fake_service.update_global_settings = AsyncMock(side_effect=RuntimeError("DB down"))
        # Patch db_service on the real (conftest-stubbed) module so the
        # `import app.services.database as _db` inside config_store picks it up
        # (import binds to whatever sys.modules returns, but parent-attribute
        # lookup also reads `app.services.database`).
        monkeypatch.setattr(sys.modules["app.services.database"], "db_service", fake_service, raising=False)

        with pytest.raises(RuntimeError):
            _run(config_store.update_overrides({"similarity_threshold": 0.8}))

        assert "similarity_threshold" not in config_store._server_config_overrides

    def test_non_persisted_key_bypasses_db(self, config_store, monkeypatch):
        fake_service = MagicMock()
        fake_service.update_global_settings = AsyncMock()
        # Patch db_service on the real (conftest-stubbed) module so the
        # `import app.services.database as _db` inside config_store picks it up
        # (import binds to whatever sys.modules returns, but parent-attribute
        # lookup also reads `app.services.database`).
        monkeypatch.setattr(sys.modules["app.services.database"], "db_service", fake_service, raising=False)

        _run(config_store.update_overrides({"lakebase_service_token": "secret"}))

        assert config_store._server_config_overrides["lakebase_service_token"] == "secret"
        fake_service.update_global_settings.assert_not_awaited()


class TestClearableModelFields:
    """PUT /settings sends `""` when the user picks 'Use default' in the model
    dropdown. The empty string must route to a DB delete — not an upsert of
    `{"value": ""}` — so the runtime fallback to the module-level default can
    actually fire."""

    def test_empty_string_model_clears_from_db_and_cache(self, config_store, monkeypatch):
        config_store._server_config_overrides["normalization_model"] = "databricks-llama-4"
        fake_service = MagicMock()
        fake_service.update_global_settings = AsyncMock()
        fake_service.delete_global_setting = AsyncMock(return_value=True)
        monkeypatch.setattr(
            sys.modules["app.services.database"],
            "db_service",
            fake_service,
            raising=False,
        )

        _run(config_store.update_overrides({"normalization_model": ""}))

        # The cleared key is removed from the cache…
        assert "normalization_model" not in config_store._server_config_overrides
        # …the DB delete ran…
        fake_service.delete_global_setting.assert_awaited_once_with("normalization_model")
        # …and we did NOT upsert an empty string as the value.
        fake_service.update_global_settings.assert_not_awaited()

    def test_all_model_fields_are_clearable(self, config_store):
        for key in ("normalization_model", "validation_model", "intent_split_model"):
            assert key in config_store._CLEARABLE_KEYS, f"{key} must be clearable"


class TestSensitiveKeyGuard:
    """_is_sensitive_key is the substring belt-and-suspenders that prevents a
    future secret-bearing key (e.g. `databricks_pat`, `oauth_token`) from being
    silently persisted to Lakebase because someone forgot to add it to
    _NON_PERSISTED_KEYS.
    """

    def test_explicit_non_persisted_key(self, config_store):
        assert config_store._is_sensitive_key("lakebase_service_token") is True

    def test_token_substring_caught(self, config_store):
        for key in ("databricks_token", "oauth_token", "MY_TOKEN"):
            assert config_store._is_sensitive_key(key) is True, key

    def test_secret_substring_caught(self, config_store):
        assert config_store._is_sensitive_key("client_secret") is True
        assert config_store._is_sensitive_key("API_SECRET") is True

    def test_pat_substring_caught(self, config_store):
        assert config_store._is_sensitive_key("databricks_pat") is True

    def test_password_substring_caught(self, config_store):
        assert config_store._is_sensitive_key("db_password") is True

    def test_api_key_substring_caught(self, config_store):
        assert config_store._is_sensitive_key("my_api_key") is True

    def test_nonsensitive_keys_pass(self, config_store):
        for key in (
            "similarity_threshold", "max_queries_per_minute", "cache_ttl_hours",
            "shared_cache", "normalization_model", "validation_model",
            "lakebase_catalog", "lakebase_schema",
        ):
            assert config_store._is_sensitive_key(key) is False, key

    def test_boundary_match_no_false_positive_on_substring(self, config_store):
        """Regression: the old `"pat" in lowered` check would false-positive on
        `patch_interval` and `path_prefix`. Boundary matching keeps the guard
        on real `_pat` tokens while letting unrelated names through."""
        for key in ("patch_interval", "path_prefix", "pattern_cache", "compatible_mode"):
            assert config_store._is_sensitive_key(key) is False, (
                f"{key!r} should not trip the sensitive-key guard — the regex "
                f"must only match at underscore-delimited boundaries"
            )

    def test_boundary_match_still_catches_token_at_boundary(self, config_store):
        """`pat` bounded by `_` or start/end is still flagged."""
        for key in ("pat", "databricks_pat", "pat_prefix", "my_pat_here"):
            assert config_store._is_sensitive_key(key) is True, key

    def test_sensitive_substring_key_not_persisted_to_db(self, config_store, monkeypatch):
        """A key NOT in _NON_PERSISTED_KEYS but matching a sensitive substring
        must still be kept in memory only. This is the regression guard for
        the old filter behavior."""
        fake_service = MagicMock()
        fake_service.update_global_settings = AsyncMock()
        monkeypatch.setattr(
            sys.modules["app.services.database"], "db_service", fake_service, raising=False,
        )

        # databricks_pat matches the "pat" substring but is NOT in _NON_PERSISTED_KEYS
        _run(config_store.update_overrides({"databricks_pat": "dapi-xxx"}))

        assert config_store._server_config_overrides["databricks_pat"] == "dapi-xxx"
        fake_service.update_global_settings.assert_not_awaited()


class TestUpdateOverridesPartialFailure:
    """The cache must never hold a value that the DB doesn't hold. If an upsert
    fails the whole batch is rejected; if a single clear fails only that key
    is skipped — the successful upserts stay in cache."""

    def test_upsert_failure_rejects_entire_batch(self, config_store, monkeypatch):
        fake_service = MagicMock()
        fake_service.update_global_settings = AsyncMock(side_effect=RuntimeError("boom"))
        fake_service.delete_global_setting = AsyncMock(return_value=True)
        monkeypatch.setattr(
            sys.modules["app.services.database"], "db_service", fake_service, raising=False,
        )

        with pytest.raises(RuntimeError):
            _run(config_store.update_overrides({
                "similarity_threshold": 0.5,
                "max_queries_per_minute": 10,
            }))

        # Neither key made it into the cache — mirrors the transactional
        # rollback of executemany on the DB side.
        assert "similarity_threshold" not in config_store._server_config_overrides
        assert "max_queries_per_minute" not in config_store._server_config_overrides

    def test_clear_failure_keeps_cache_value_but_applies_upserts(self, config_store, monkeypatch):
        """A partial failure in the clear phase must leave the cleared-but-failed
        key untouched in the cache (so it stays in sync with the DB, which
        still holds it), while successful upserts in the same batch still apply."""
        config_store._server_config_overrides["normalization_model"] = "old-model"

        fake_service = MagicMock()
        fake_service.update_global_settings = AsyncMock()
        fake_service.delete_global_setting = AsyncMock(side_effect=RuntimeError("delete failed"))
        monkeypatch.setattr(
            sys.modules["app.services.database"], "db_service", fake_service, raising=False,
        )

        _run(config_store.update_overrides({
            "similarity_threshold": 0.8,          # upsert — should succeed
            "normalization_model": "",            # clear — will fail
        }))

        # Upsert applied, cache reflects DB write.
        assert config_store._server_config_overrides["similarity_threshold"] == 0.8
        # Clear failed at DB layer — cache MUST NOT drop the key, else a restart
        # would reintroduce "old-model" from the DB.
        assert config_store._server_config_overrides["normalization_model"] == "old-model"

    def test_db_service_missing_skips_cache_for_persisted_keys(self, config_store, monkeypatch):
        """When storage isn't initialized yet, we must not apply the persisted-
        key half of the batch to the cache — otherwise the cached value would
        be lost on restart (no DB row backs it)."""
        monkeypatch.setattr(
            sys.modules["app.services.database"], "db_service", None, raising=False,
        )

        _run(config_store.update_overrides({
            "similarity_threshold": 0.5,
            "lakebase_service_token": "secret",
        }))

        # Sensitive in-memory key still applied (nothing to persist).
        assert config_store._server_config_overrides["lakebase_service_token"] == "secret"
        # Persisted key NOT applied — we can't commit to DB, so don't diverge.
        assert "similarity_threshold" not in config_store._server_config_overrides
