"""
Tests for the tracing wrapper.

The wrapper is a thin shim over mlflow so the point of these tests is to lock
in the invariants that matter when mlflow isn't available or tracing is off:
- span() yields a noop when disabled; the `with` block still runs
- init_tracing never raises and never flips _enabled on a bad env
- current_trace_id returns None when disabled
"""
import importlib
import os
import sys
from unittest.mock import patch

import pytest


@pytest.fixture
def tracing_fresh(monkeypatch):
    """Load a fresh copy of app.services.tracing with a clean _enabled=False.

    conftest stubs mlflow out of sys.modules. We leave it absent for these tests
    so we exercise the import-error paths honestly.
    """
    # Strip mlflow so init_tracing takes the import-fail branch by default
    for k in list(sys.modules.keys()):
        if k == "mlflow" or k.startswith("mlflow."):
            del sys.modules[k]
    sys.modules.pop("app.services.tracing", None)
    # Clean env — individual tests re-set what they need
    monkeypatch.delenv("TRACING_ENABLED", raising=False)
    monkeypatch.delenv("MLFLOW_EXPERIMENT_NAME", raising=False)
    mod = importlib.import_module("app.services.tracing")
    return mod


class TestEnableGate:
    def test_disabled_by_default(self, tracing_fresh):
        assert tracing_fresh.is_enabled() is False

    def test_env_unset_stays_disabled(self, tracing_fresh):
        import asyncio
        asyncio.run(tracing_fresh.init_tracing())
        assert tracing_fresh.is_enabled() is False

    def test_env_false_stays_disabled(self, tracing_fresh, monkeypatch):
        monkeypatch.setenv("TRACING_ENABLED", "false")
        import asyncio
        asyncio.run(tracing_fresh.init_tracing())
        assert tracing_fresh.is_enabled() is False

    def test_env_true_without_mlflow_stays_disabled(self, tracing_fresh, monkeypatch):
        """If TRACING_ENABLED=true but mlflow import fails, we log and stay off —
        app boot must never fail because of tracing."""
        monkeypatch.setenv("TRACING_ENABLED", "true")
        # Block mlflow import: sys.modules[name] = None makes Python raise ImportError
        # on any subsequent `import mlflow` call.
        monkeypatch.setitem(sys.modules, "mlflow", None)
        import asyncio
        asyncio.run(tracing_fresh.init_tracing())
        assert tracing_fresh.is_enabled() is False

    def test_env_true_with_mlflow_enables(self, tracing_fresh, monkeypatch):
        """With TRACING_ENABLED=true and mlflow importable, we flip enabled=True.
        No experiment name → still enabled, with a warning."""
        import types
        monkeypatch.setenv("TRACING_ENABLED", "true")
        # Inject a minimal fake mlflow that exposes just what init_tracing touches
        fake_mlflow = types.ModuleType("mlflow")
        fake_mlflow.get_tracking_uri = lambda: "databricks"
        fake_mlflow.set_tracking_uri = lambda uri: None
        fake_mlflow.set_registry_uri = lambda uri: None
        fake_mlflow.set_experiment = lambda name: None
        fake_mlflow.config = types.SimpleNamespace(enable_async_logging=lambda: None)
        monkeypatch.setitem(sys.modules, "mlflow", fake_mlflow)

        import asyncio
        asyncio.run(tracing_fresh.init_tracing())
        assert tracing_fresh.is_enabled() is True

    def test_truthy_values(self, tracing_fresh):
        assert tracing_fresh._truthy("1") is True
        assert tracing_fresh._truthy("true") is True
        assert tracing_fresh._truthy("True") is True
        assert tracing_fresh._truthy("yes") is True
        assert tracing_fresh._truthy("on") is True
        assert tracing_fresh._truthy("0") is False
        assert tracing_fresh._truthy("") is False
        assert tracing_fresh._truthy("maybe") is False


class TestSpanNoop:
    def test_span_yields_noop_when_disabled(self, tracing_fresh):
        with tracing_fresh.span("test.span", span_type="CHAIN") as s:
            # All methods on noop should no-op (not raise)
            s.set_inputs({"x": 1})
            s.set_outputs({"y": 2})
            s.set_attribute("k", "v")
            s.set_attributes({"a": 1, "b": 2})
            s.set_status("OK")
            assert s.trace_id is None

    def test_current_trace_id_none_when_disabled(self, tracing_fresh):
        assert tracing_fresh.current_trace_id() is None

    def test_span_with_all_kwargs_noop(self, tracing_fresh):
        """Pass every kwarg we document; ensure noop still yields."""
        with tracing_fresh.span(
            "root",
            span_type="AGENT",
            inputs={"q": "hello"},
            attributes={"router_id": "r1"},
        ) as s:
            s.set_outputs({"ok": True})


class TestSpanActive:
    """When tracing is enabled, span() should delegate to mlflow.start_span."""

    def test_enabled_span_calls_mlflow(self, tracing_fresh, monkeypatch):
        # Force the enabled branch without going through init_tracing; install a
        # fake mlflow into sys.modules so the deferred import inside span() finds it.
        import types
        fake = types.ModuleType("mlflow")

        start_calls = []
        span_calls = []

        class _FakeSpan:
            trace_id = "trace-abc"

            def set_inputs(self, payload):
                span_calls.append(("set_inputs", payload))

            def set_attribute(self, k, v):
                span_calls.append(("set_attribute", k, v))

            def set_outputs(self, payload):
                span_calls.append(("set_outputs", payload))

        class _Ctx:
            def __enter__(self_inner):
                span_calls.append("enter")
                return _FakeSpan()

            def __exit__(self_inner, *a):
                span_calls.append("exit")
                return False

        fake.start_span = lambda **kw: (start_calls.append(kw) or _Ctx())
        sys.modules["mlflow"] = fake
        tracing_fresh._enabled = True

        try:
            with tracing_fresh.span(
                "router.select",
                span_type="AGENT",
                inputs={"q": "hi"},
                attributes={"router_id": "r1", "n_members": 8},
            ) as s:
                assert s.trace_id == "trace-abc"
                s.set_outputs({"n_picks": 2})
        finally:
            tracing_fresh._enabled = False
            sys.modules.pop("mlflow", None)

        # start_span only gets name + span_type — inputs/attributes are set on the span
        assert len(start_calls) == 1
        assert start_calls[0] == {"name": "router.select", "span_type": "AGENT"}

        # Inputs + each attribute + user-called outputs are set on the span object
        assert ("set_inputs", {"q": "hi"}) in span_calls
        assert ("set_attribute", "router_id", "r1") in span_calls
        assert ("set_attribute", "n_members", 8) in span_calls
        assert ("set_outputs", {"n_picks": 2}) in span_calls
        assert "enter" in span_calls and "exit" in span_calls

    def test_enabled_span_falls_back_to_noop_on_mlflow_error(self, tracing_fresh):
        """If mlflow.start_span raises mid-request, we degrade to noop rather than
        propagating — a tracing bug should never fail a user query."""
        import types
        fake = types.ModuleType("mlflow")

        def _boom(**kw):
            raise RuntimeError("mlflow broken")

        fake.start_span = _boom
        sys.modules["mlflow"] = fake
        tracing_fresh._enabled = True

        try:
            with tracing_fresh.span("test") as s:
                # Should be noop, not raise
                s.set_outputs({"x": 1})
                assert s.trace_id is None
        finally:
            tracing_fresh._enabled = False
            sys.modules.pop("mlflow", None)
