"""
Unit tests for RuntimeSettings fallback semantics.

Regression coverage for issue #26: numeric override fields (similarity_threshold,
max_queries_per_minute, cache_ttl_hours) must use `is not None` not truthy checks,
so a user-provided 0 is preserved rather than silently replaced by the base default.

conftest.py stubs out app.runtime_config for other tests; we reload the real
module here against a lightweight app.config / app.models shim so the real
property logic under test runs end-to-end.
"""
import importlib
import sys
import types
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def runtime_config_module():
    """Load the real app.runtime_config with a minimal app.config / app.models stub."""
    # app.config.get_settings() — provide defaults the real module reads at import time.
    base = types.SimpleNamespace(
        databricks_host="https://example.cloud.databricks.com",
        genie_space_id="",
        sql_warehouse_id="",
        similarity_threshold=0.92,
        max_queries_per_minute=5,
        cache_ttl_hours=24.0,
        embedding_provider="databricks",
        databricks_embedding_endpoint="databricks-gte-large-en",
        app_env="test",
        storage_backend="pgvector",
        is_databricks=False,
        shared_cache=True,
        lakebase_catalog="default",
        lakebase_schema="public",
        pgvector_table_name="cached_queries",
        postgres_connection_string="",
    )
    config_stub = types.ModuleType("app.config")
    config_stub.get_settings = MagicMock(return_value=base)
    sys.modules["app.config"] = config_stub

    # app.models.RuntimeConfig — use a minimal dataclass-like stand-in. The
    # real module only reads attributes off the object.
    class _RuntimeConfig(types.SimpleNamespace):
        pass
    models_stub = types.ModuleType("app.models")
    models_stub.RuntimeConfig = _RuntimeConfig
    sys.modules["app.models"] = models_stub

    # Force a fresh import of the real runtime_config
    sys.modules.pop("app.runtime_config", None)
    module = importlib.import_module("app.runtime_config")
    importlib.reload(module)

    yield module, _RuntimeConfig, base


def _build_rc(RuntimeConfig, **overrides):
    """Build a RuntimeConfig with only the fields we care about set."""
    defaults = dict(
        gateway_id=None,
        genie_space_id=None,
        sql_warehouse_id=None,
        similarity_threshold=None,
        max_queries_per_minute=None,
        embedding_provider=None,
        databricks_embedding_endpoint=None,
        storage_backend=None,
        cache_ttl_hours=None,
        lakebase_instance_name=None,
        lakebase_catalog=None,
        lakebase_schema=None,
        cache_table_name=None,
        query_log_table_name=None,
        shared_cache=None,
        question_normalization_enabled=None,
        cache_validation_enabled=None,
        caching_enabled=None,
        intent_split_enabled=None,
        normalization_model=None,
        validation_model=None,
        intent_split_model=None,
    )
    defaults.update(overrides)
    return RuntimeConfig(**defaults)


class TestNumericFallback:
    """Issue #26: numeric fields must preserve user-set 0, not fall through."""

    def test_similarity_threshold_zero_is_preserved(self, runtime_config_module):
        module, RC, base = runtime_config_module
        rs = module.RuntimeSettings(_build_rc(RC, similarity_threshold=0.0), user_token="t")
        assert rs.similarity_threshold == 0.0, (
            "similarity_threshold=0 was dropped — a user-set 'match everything' "
            "threshold must not fall through to base default"
        )

    def test_similarity_threshold_none_falls_through(self, runtime_config_module):
        module, RC, base = runtime_config_module
        rs = module.RuntimeSettings(_build_rc(RC, similarity_threshold=None), user_token="t")
        assert rs.similarity_threshold == base.similarity_threshold

    def test_similarity_threshold_nonzero_is_preserved(self, runtime_config_module):
        module, RC, base = runtime_config_module
        rs = module.RuntimeSettings(_build_rc(RC, similarity_threshold=0.7), user_token="t")
        assert rs.similarity_threshold == 0.7

    def test_max_queries_per_minute_zero_is_preserved(self, runtime_config_module):
        module, RC, base = runtime_config_module
        rs = module.RuntimeSettings(_build_rc(RC, max_queries_per_minute=0), user_token="t")
        assert rs.max_queries_per_minute == 0, (
            "max_queries_per_minute=0 was dropped — a user-set 'block all traffic' "
            "rate limit must not fall through to base default"
        )

    def test_max_queries_per_minute_none_falls_through(self, runtime_config_module):
        module, RC, base = runtime_config_module
        rs = module.RuntimeSettings(_build_rc(RC, max_queries_per_minute=None), user_token="t")
        assert rs.max_queries_per_minute == base.max_queries_per_minute

    def test_cache_ttl_zero_is_preserved(self, runtime_config_module):
        """cache_ttl_hours=0 means 'unlimited' per storage_pgvector — must not fall through."""
        module, RC, base = runtime_config_module
        rs = module.RuntimeSettings(_build_rc(RC, cache_ttl_hours=0.0), user_token="t")
        assert rs.cache_ttl_hours == 0.0

    def test_cache_ttl_none_falls_through(self, runtime_config_module):
        module, RC, base = runtime_config_module
        rs = module.RuntimeSettings(_build_rc(RC, cache_ttl_hours=None), user_token="t")
        assert rs.cache_ttl_hours == base.cache_ttl_hours


class TestBooleanFallback:
    """Boolean fields were already using `is not None` — lock that behavior in."""

    def test_shared_cache_false_is_preserved(self, runtime_config_module):
        module, RC, base = runtime_config_module
        rs = module.RuntimeSettings(_build_rc(RC, shared_cache=False), user_token="t")
        assert rs.shared_cache is False

    def test_shared_cache_none_falls_through(self, runtime_config_module):
        module, RC, base = runtime_config_module
        rs = module.RuntimeSettings(_build_rc(RC, shared_cache=None), user_token="t")
        assert rs.shared_cache is base.shared_cache


class TestModelFieldFallback:
    """Issue #26: per-service LLM endpoint overrides must:
    - Prefer runtime (gateway) value when set
    - Treat empty string as 'unset' (matches update_gateway's "" → NULL normalization)
    - Fall through to global (config_store.get_effective_setting) when runtime is None/""
    - Fall through to None when neither is set
    """

    def _patch_global(self, module, monkeypatch, **kv):
        """Override get_effective_setting's return value for specific keys.

        Ensures app.api.config_store is registered in sys.modules before
        patching — other tests (test_config_store) remove it during teardown,
        so the module may be absent depending on test order.
        """
        if "app.api.config_store" not in sys.modules:
            cs_stub = types.ModuleType("app.api.config_store")
            cs_stub.get_effective_setting = lambda _k: None
            sys.modules["app.api.config_store"] = cs_stub
            if "app.api" in sys.modules:
                sys.modules["app.api"].config_store = cs_stub
        def _fake(key):
            return kv.get(key)
        monkeypatch.setitem(
            sys.modules["app.api.config_store"].__dict__,
            "get_effective_setting",
            _fake,
        )

    def test_normalization_model_runtime_wins(self, runtime_config_module, monkeypatch):
        module, RC, base = runtime_config_module
        self._patch_global(module, monkeypatch, normalization_model="global-model")
        rs = module.RuntimeSettings(
            _build_rc(RC, normalization_model="runtime-model"), user_token="t"
        )
        assert rs.normalization_model == "runtime-model"

    def test_normalization_model_empty_string_falls_through(self, runtime_config_module, monkeypatch):
        """Empty string must be treated as unset (gateway cleared the override)."""
        module, RC, base = runtime_config_module
        self._patch_global(module, monkeypatch, normalization_model="global-model")
        rs = module.RuntimeSettings(
            _build_rc(RC, normalization_model=""), user_token="t"
        )
        assert rs.normalization_model == "global-model"

    def test_normalization_model_none_falls_through(self, runtime_config_module, monkeypatch):
        module, RC, base = runtime_config_module
        self._patch_global(module, monkeypatch, normalization_model="global-model")
        rs = module.RuntimeSettings(
            _build_rc(RC, normalization_model=None), user_token="t"
        )
        assert rs.normalization_model == "global-model"

    def test_normalization_model_no_global_returns_none(self, runtime_config_module, monkeypatch):
        module, RC, base = runtime_config_module
        self._patch_global(module, monkeypatch)  # no globals set
        rs = module.RuntimeSettings(
            _build_rc(RC, normalization_model=None), user_token="t"
        )
        assert rs.normalization_model is None

    def test_normalization_model_empty_global_returns_none(self, runtime_config_module, monkeypatch):
        """Global stored as empty string must not be returned as a valid endpoint."""
        module, RC, base = runtime_config_module
        self._patch_global(module, monkeypatch, normalization_model="")
        rs = module.RuntimeSettings(
            _build_rc(RC, normalization_model=None), user_token="t"
        )
        assert rs.normalization_model is None

    def test_validation_model_resolves_like_normalization(self, runtime_config_module, monkeypatch):
        module, RC, base = runtime_config_module
        self._patch_global(module, monkeypatch, validation_model="global-val")
        rs_runtime = module.RuntimeSettings(
            _build_rc(RC, validation_model="runtime-val"), user_token="t"
        )
        rs_empty = module.RuntimeSettings(_build_rc(RC, validation_model=""), user_token="t")
        rs_none = module.RuntimeSettings(_build_rc(RC, validation_model=None), user_token="t")
        assert rs_runtime.validation_model == "runtime-val"
        assert rs_empty.validation_model == "global-val"
        assert rs_none.validation_model == "global-val"

    def test_intent_split_model_resolves_like_normalization(self, runtime_config_module, monkeypatch):
        module, RC, base = runtime_config_module
        self._patch_global(module, monkeypatch, intent_split_model="global-intent")
        rs_runtime = module.RuntimeSettings(
            _build_rc(RC, intent_split_model="runtime-intent"), user_token="t"
        )
        rs_empty = module.RuntimeSettings(_build_rc(RC, intent_split_model=""), user_token="t")
        assert rs_runtime.intent_split_model == "runtime-intent"
        assert rs_empty.intent_split_model == "global-intent"
