"""
Tests for gateway create body → storage-dict translation.

Issue #26 items 1 & 2: gateway defaults were hard-coded at create time, so a
later change to a global setting never propagated. The fix leaves NULL for
every field the user didn't explicitly set; _build_runtime_settings resolves
NULL dynamically against the current global. These tests lock in the
"None-in → None-out" invariant so that promise holds.
"""
import importlib
import sys
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixture: import gateway_routes with the minimum stubs it needs
# ---------------------------------------------------------------------------

@pytest.fixture
def gateway_routes(monkeypatch):
    """Load app.api.gateway_routes fresh, stubbing its heavyweight deps."""
    # Stub httpx (imported at module top) and fastapi (also imported there)
    if "httpx" not in sys.modules:
        httpx_stub = types.ModuleType("httpx")
        httpx_stub.AsyncClient = MagicMock()
        sys.modules["httpx"] = httpx_stub

    if "fastapi" not in sys.modules:
        fastapi_stub = types.ModuleType("fastapi")
        fastapi_stub.APIRouter = MagicMock()
        fastapi_stub.HTTPException = type("HTTPException", (Exception,), {
            "__init__": lambda self, status_code=500, detail="": setattr(self, "status_code", status_code) or setattr(self, "detail", detail) or None
        })
        fastapi_stub.Request = MagicMock()
        sys.modules["fastapi"] = fastapi_stub

    # Stub pydantic if missing (real models require it)
    if "pydantic" not in sys.modules:
        try:
            import pydantic  # noqa: F401
        except ImportError:
            pytest.skip("pydantic not installed")

    # Real GatewayCreateRequest (swap out the conftest stub of app.models)
    sys.modules.pop("app.models", None)
    sys.modules.pop("app.api.gateway_routes", None)

    # Ensure app.config and app.auth stubs expose what gateway_routes imports
    sys.modules["app.config"].get_settings = MagicMock(
        return_value=types.SimpleNamespace(databricks_host="")
    )
    sys.modules["app.auth"].ensure_https = lambda h: h

    # app.api.config_store: get_effective_setting must be controllable.
    # Other test files may have popped this from sys.modules; re-stub it so
    # the gateway_routes import finds it.
    if "app.api.config_store" not in sys.modules:
        cs_stub = types.ModuleType("app.api.config_store")
        sys.modules["app.api.config_store"] = cs_stub
        if "app.api" in sys.modules:
            sys.modules["app.api"].config_store = cs_stub
    cs_stub = sys.modules["app.api.config_store"]
    cs_stub.get_effective_setting = MagicMock(return_value=None)
    cs_stub.get_overrides = MagicMock(return_value={})
    cs_stub.update_overrides = MagicMock()

    # auth_helpers (require_role etc.) — unused in the function we're testing
    ah_stub = types.ModuleType("app.api.auth_helpers")
    ah_stub.extract_bearer_token_optional = MagicMock()
    ah_stub.resolve_user_token_optional = MagicMock()
    ah_stub.require_role = MagicMock()
    sys.modules["app.api.auth_helpers"] = ah_stub
    sys.modules["app.api"].auth_helpers = ah_stub

    # Import real models
    import app.models  # noqa: F401

    module = importlib.import_module("app.api.gateway_routes")
    return module, cs_stub


def _body_kwargs(**overrides):
    """Minimal valid GatewayCreateRequest kwargs."""
    base = dict(name="gw1", genie_space_id="space-123")
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _unset_if_blank helper
# ---------------------------------------------------------------------------

class TestUnsetIfBlank:
    def test_none_stays_none(self, gateway_routes):
        mod, _ = gateway_routes
        assert mod._unset_if_blank(None) is None

    def test_empty_string_becomes_none(self, gateway_routes):
        mod, _ = gateway_routes
        assert mod._unset_if_blank("") is None

    def test_nonblank_string_passes_through(self, gateway_routes):
        mod, _ = gateway_routes
        assert mod._unset_if_blank("my-model") == "my-model"

    def test_falsy_nonblank_passes_through(self, gateway_routes):
        """0 and False are legitimate model-field values in some contexts and
        shouldn't be nulled by a truthy check."""
        mod, _ = gateway_routes
        assert mod._unset_if_blank(0) == 0
        assert mod._unset_if_blank(False) is False


# ---------------------------------------------------------------------------
# _build_gateway_config_from_body
# ---------------------------------------------------------------------------

class TestBuildGatewayConfigFromBody:
    def _build(self, mod, **body_overrides):
        from app.models import GatewayCreateRequest
        body = GatewayCreateRequest(**_body_kwargs(**body_overrides))
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return mod._build_gateway_config_from_body(body, user_email="u@x", now=now)

    def test_unset_numeric_fields_become_none(self, gateway_routes):
        """A minimal body stores NULL for every optional numeric/boolean.
        _build_runtime_settings will resolve NULL → current global dynamically."""
        mod, _ = gateway_routes
        config = self._build(mod)
        assert config["similarity_threshold"] is None
        assert config["max_queries_per_minute"] is None
        assert config["cache_ttl_hours"] is None
        assert config["shared_cache"] is None
        assert config["question_normalization_enabled"] is None
        assert config["cache_validation_enabled"] is None
        assert config["caching_enabled"] is None
        assert config["intent_split_enabled"] is None

    def test_caching_enabled_preserved_when_set(self, gateway_routes):
        """A user who explicitly disables semantic caching at create time must
        see that choice land in the DB; the `caching_enabled: False` case is
        exactly the kind of falsy value that truthy-coalescing would drop."""
        mod, _ = gateway_routes
        config_off = self._build(mod, caching_enabled=False)
        assert config_off["caching_enabled"] is False
        config_on = self._build(mod, caching_enabled=True)
        assert config_on["caching_enabled"] is True

    def test_user_set_values_are_preserved(self, gateway_routes):
        mod, _ = gateway_routes
        config = self._build(mod, similarity_threshold=0.5, max_queries_per_minute=10,
                             cache_ttl_hours=48.0, shared_cache=False,
                             question_normalization_enabled=True, intent_split_enabled=False)
        assert config["similarity_threshold"] == 0.5
        assert config["max_queries_per_minute"] == 10
        assert config["cache_ttl_hours"] == 48.0
        assert config["shared_cache"] is False
        assert config["question_normalization_enabled"] is True
        assert config["intent_split_enabled"] is False

    def test_zero_threshold_preserved_not_nulled(self, gateway_routes):
        """0.0 is a valid 'match everything' threshold. It must NOT be nulled
        by a truthy check (this was the item #4b bug for runtime, same trap
        at create time)."""
        mod, _ = gateway_routes
        config = self._build(mod, similarity_threshold=0.0)
        assert config["similarity_threshold"] == 0.0

    def test_zero_qpm_preserved_not_nulled(self, gateway_routes):
        mod, _ = gateway_routes
        config = self._build(mod, max_queries_per_minute=0)
        assert config["max_queries_per_minute"] == 0

    def test_unset_model_fields_become_none(self, gateway_routes):
        mod, _ = gateway_routes
        config = self._build(mod)
        assert config["normalization_model"] is None
        assert config["validation_model"] is None
        assert config["intent_split_model"] is None
        assert config["embedding_provider"] is None
        assert config["databricks_embedding_endpoint"] is None

    def test_empty_string_model_fields_become_none(self, gateway_routes):
        """Empty string from the UI ("no selection") is treated the same as
        NULL so the runtime fallback to the global kicks in."""
        mod, _ = gateway_routes
        config = self._build(mod, normalization_model="", validation_model="",
                             intent_split_model="")
        assert config["normalization_model"] is None
        assert config["validation_model"] is None
        assert config["intent_split_model"] is None

    def test_user_set_model_fields_preserved(self, gateway_routes):
        mod, _ = gateway_routes
        config = self._build(mod, normalization_model="custom-norm",
                             validation_model="custom-val",
                             intent_split_model="custom-intent")
        assert config["normalization_model"] == "custom-norm"
        assert config["validation_model"] == "custom-val"
        assert config["intent_split_model"] == "custom-intent"

    def test_sql_warehouse_id_falls_back_to_global(self, gateway_routes):
        """sql_warehouse_id has a NOT NULL DB constraint, so it's the one
        field that still snapshots the global at create time."""
        mod, cs = gateway_routes
        cs.get_effective_setting.side_effect = lambda k: "global-wh" if k == "sql_warehouse_id" else None
        config = self._build(mod)
        assert config["sql_warehouse_id"] == "global-wh"

    def test_sql_warehouse_id_body_wins_over_global(self, gateway_routes):
        mod, cs = gateway_routes
        cs.get_effective_setting.side_effect = lambda k: "global-wh" if k == "sql_warehouse_id" else None
        config = self._build(mod, sql_warehouse_id="body-wh")
        assert config["sql_warehouse_id"] == "body-wh"

    def test_sql_warehouse_id_empty_when_no_global(self, gateway_routes):
        """RuntimeSettings.sql_warehouse_id's .strip() check routes empty
        string through to the env default — no DB constraint violation."""
        mod, cs = gateway_routes
        cs.get_effective_setting.return_value = None
        config = self._build(mod)
        assert config["sql_warehouse_id"] == ""


# ---------------------------------------------------------------------------
# update_gateway empty-string normalization — test the SQL param-build logic
# ---------------------------------------------------------------------------

class TestUpdateGatewayParamBuild:
    """storage_pgvector.update_gateway normalizes '' → None for clearable text
    fields so the runtime fallback to the global kicks in after a user clears
    a dropdown. We validate the transformation by exercising the same
    allowlist / clearable-set logic."""

    def test_clearable_fields_empty_string_becomes_none(self):
        # Replicate the transformation inline; any refactor in the real
        # update_gateway should either keep this invariant or update this test.
        clearable = {"normalization_model", "validation_model", "intent_split_model"}
        allowed = {"name", "similarity_threshold"} | clearable

        updates = {"normalization_model": "", "validation_model": "custom", "name": "x"}

        built = []
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key in clearable and value == "":
                value = None
            elif value is None:
                continue
            built.append((key, value))

        as_dict = dict(built)
        assert as_dict["normalization_model"] is None  # cleared → NULL
        assert as_dict["validation_model"] == "custom"  # explicit value kept
        assert as_dict["name"] == "x"

    def test_none_skipped_entirely(self):
        """A None in updates means 'no change' — the field isn't added to
        the SET clause (preserves existing DB value)."""
        clearable = {"normalization_model"}
        allowed = {"name"} | clearable
        updates = {"normalization_model": None, "name": "x"}

        built = {}
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key in clearable and value == "":
                value = None
            elif value is None:
                continue
            built[key] = value

        assert "normalization_model" not in built
        assert built["name"] == "x"
