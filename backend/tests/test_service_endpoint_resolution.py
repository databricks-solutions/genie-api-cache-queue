"""
Tests for per-service LLM endpoint resolution.

Issue #26 item 3: the UI's normalization_model / validation_model /
intent_split_model dropdowns were ignored because each service hard-coded its
endpoint. The fix threads runtime_settings.*_model through each service's
`_get_workspace_client()` as the endpoint name. These tests lock that in so a
future refactor can't silently break the wiring again.
"""
import importlib
import sys
import types
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Shared fixture: stub databricks.sdk.core.Config (conftest only stubs
# databricks.sdk) and make WorkspaceClient a no-op callable so importing the
# services doesn't require the real SDK.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _stub_sdk():
    databricks = sys.modules.setdefault("databricks", types.ModuleType("databricks"))
    sdk = types.ModuleType("databricks.sdk")
    sdk.WorkspaceClient = MagicMock(return_value=MagicMock(name="ws_client"))
    sdk_core = types.ModuleType("databricks.sdk.core")
    sdk_core.Config = MagicMock(return_value=MagicMock(name="sdk_config"))
    databricks.sdk = sdk
    sys.modules["databricks"] = databricks
    sys.modules["databricks.sdk"] = sdk
    sys.modules["databricks.sdk.core"] = sdk_core

    # Make sure app.config stub has the attributes the service imports at load
    sys.modules["app.config"].get_settings = MagicMock(
        return_value=types.SimpleNamespace(databricks_host="https://example.cloud.databricks.com")
    )
    yield


def _fresh_import(name: str):
    """Import a fresh copy of a service module."""
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def _rs(model_attr: str, model_value, *, token="t", host="https://h"):
    """Build a minimal runtime_settings stand-in exposing one model field."""
    ns = types.SimpleNamespace(databricks_token=token, databricks_host=host)
    setattr(ns, model_attr, model_value)
    return ns


# ---------------------------------------------------------------------------
# question_normalizer
# ---------------------------------------------------------------------------

class TestQuestionNormalizerEndpoint:
    def test_uses_runtime_model_when_set(self):
        mod = _fresh_import("app.services.question_normalizer")
        _, endpoint = mod._get_workspace_client(_rs("normalization_model", "my-custom-model"))
        assert endpoint == "my-custom-model"

    def test_falls_back_to_default_when_runtime_none(self):
        mod = _fresh_import("app.services.question_normalizer")
        _, endpoint = mod._get_workspace_client(_rs("normalization_model", None))
        assert endpoint == mod.QUESTION_NORMALIZATION_LLM_ENDPOINT

    def test_falls_back_to_default_when_runtime_empty(self):
        mod = _fresh_import("app.services.question_normalizer")
        _, endpoint = mod._get_workspace_client(_rs("normalization_model", ""))
        assert endpoint == mod.QUESTION_NORMALIZATION_LLM_ENDPOINT

    def test_default_when_runtime_settings_is_none(self):
        mod = _fresh_import("app.services.question_normalizer")
        _, endpoint = mod._get_workspace_client(None)
        assert endpoint == mod.QUESTION_NORMALIZATION_LLM_ENDPOINT


# ---------------------------------------------------------------------------
# cache_validator
# ---------------------------------------------------------------------------

class TestCacheValidatorEndpoint:
    def test_uses_runtime_model_when_set(self):
        mod = _fresh_import("app.services.cache_validator")
        _, endpoint = mod._get_workspace_client(_rs("validation_model", "custom-validator"))
        assert endpoint == "custom-validator"

    def test_falls_back_to_default_when_runtime_none(self):
        mod = _fresh_import("app.services.cache_validator")
        _, endpoint = mod._get_workspace_client(_rs("validation_model", None))
        assert endpoint == mod.CACHE_VALIDATION_LLM_ENDPOINT

    def test_default_when_runtime_settings_is_none(self):
        mod = _fresh_import("app.services.cache_validator")
        _, endpoint = mod._get_workspace_client(None)
        assert endpoint == mod.CACHE_VALIDATION_LLM_ENDPOINT


# ---------------------------------------------------------------------------
# intent_splitter
# ---------------------------------------------------------------------------

class TestIntentSplitterEndpoint:
    def test_uses_runtime_model_when_set(self):
        mod = _fresh_import("app.services.intent_splitter")
        _, endpoint = mod._get_workspace_client(_rs("intent_split_model", "custom-intent"))
        assert endpoint == "custom-intent"

    def test_falls_back_to_default_when_runtime_none(self):
        mod = _fresh_import("app.services.intent_splitter")
        _, endpoint = mod._get_workspace_client(_rs("intent_split_model", None))
        assert endpoint == mod.INTENT_SPLIT_LLM_ENDPOINT

    def test_default_when_runtime_settings_is_none(self):
        mod = _fresh_import("app.services.intent_splitter")
        _, endpoint = mod._get_workspace_client(None)
        assert endpoint == mod.INTENT_SPLIT_LLM_ENDPOINT
