"""
Tests for the tracing wrapper.

The wrapper is a thin shim over mlflow with two key invariants:
  1. Direct (non-router) callers must produce ZERO traces, even when
     TRACING_ENABLED=true. This is enforced via a contextvar that only
     start_router_root_span sets.
  2. A failure inside mlflow must never propagate to the caller — degrade
     to a noop and let the request continue.
"""
import importlib
import sys
import types

import pytest


@pytest.fixture
def tracing_fresh(monkeypatch):
    """Load a fresh copy of app.services.tracing with a clean _enabled=False."""
    for k in list(sys.modules.keys()):
        if k == "mlflow" or k.startswith("mlflow."):
            del sys.modules[k]
    sys.modules.pop("app.services.tracing", None)
    monkeypatch.delenv("TRACING_ENABLED", raising=False)
    monkeypatch.delenv("MLFLOW_EXPERIMENT_NAME", raising=False)
    mod = importlib.import_module("app.services.tracing")
    return mod


def _install_fake_mlflow(monkeypatch, *, start_calls=None, span_factory=None, raise_on_start=False):
    """Install a fake mlflow module that records start_span calls."""
    fake = types.ModuleType("mlflow")
    fake.get_tracking_uri = lambda: "databricks"
    fake.set_tracking_uri = lambda uri: None
    fake.set_registry_uri = lambda uri: None
    fake.config = types.SimpleNamespace(enable_async_logging=lambda: None)

    def _start_span(**kwargs):
        if start_calls is not None:
            start_calls.append(kwargs)
        if raise_on_start:
            raise RuntimeError("mlflow broken")
        return span_factory() if span_factory else _FakeCtx()

    fake.start_span = _start_span
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    return fake


class _FakeSpan:
    trace_id = "trace-abc"

    def __init__(self):
        self.calls = []

    def set_inputs(self, payload):
        self.calls.append(("set_inputs", payload))

    def set_attribute(self, k, v):
        self.calls.append(("set_attribute", k, v))

    def set_outputs(self, payload):
        self.calls.append(("set_outputs", payload))

    def set_attributes(self, payload):
        self.calls.append(("set_attributes", payload))

    def set_status(self, status):
        self.calls.append(("set_status", status))


class _FakeCtx:
    def __init__(self):
        self.span = _FakeSpan()

    def __enter__(self):
        return self.span

    def __exit__(self, *a):
        return False


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
        monkeypatch.setenv("TRACING_ENABLED", "true")
        monkeypatch.setitem(sys.modules, "mlflow", None)
        import asyncio
        asyncio.run(tracing_fresh.init_tracing())
        assert tracing_fresh.is_enabled() is False

    def test_env_true_with_mlflow_enables(self, tracing_fresh, monkeypatch):
        monkeypatch.setenv("TRACING_ENABLED", "true")
        _install_fake_mlflow(monkeypatch)
        import asyncio
        asyncio.run(tracing_fresh.init_tracing())
        assert tracing_fresh.is_enabled() is True

    def test_truthy_values(self, tracing_fresh):
        assert tracing_fresh._truthy("1") is True
        assert tracing_fresh._truthy("true") is True
        assert tracing_fresh._truthy("yes") is True
        assert tracing_fresh._truthy("on") is True
        assert tracing_fresh._truthy("0") is False
        assert tracing_fresh._truthy("") is False
        assert tracing_fresh._truthy("maybe") is False


class TestSpanNoopWhenDisabled:
    def test_span_yields_noop_when_disabled(self, tracing_fresh):
        with tracing_fresh.span("test.span") as s:
            s.set_inputs({"x": 1})
            s.set_outputs({"y": 2})
            s.set_attribute("k", "v")
            s.set_attributes({"a": 1})
            s.set_status("OK")
            assert s.trace_id is None

    def test_current_trace_id_none_when_disabled(self, tracing_fresh):
        assert tracing_fresh.current_trace_id() is None


class TestSpanRequiresRouterContext:
    """The contextvar gate is what keeps direct gateway calls untraced.

    span() must noop unless we're inside a start_router_root_span block.
    Even with _enabled=True, a child span() outside the root context emits
    nothing.
    """

    def test_span_noop_when_enabled_but_no_router_ctx(self, tracing_fresh, monkeypatch):
        start_calls = []
        _install_fake_mlflow(monkeypatch, start_calls=start_calls)
        tracing_fresh._enabled = True
        try:
            assert tracing_fresh.is_router_context_active() is False
            with tracing_fresh.span("gateway.cache.lookup") as s:
                s.set_outputs({"hit": False})
                assert s.trace_id is None
        finally:
            tracing_fresh._enabled = False
        # mlflow.start_span must NOT have been called
        assert start_calls == []

    def test_span_emits_when_inside_router_root(self, tracing_fresh, monkeypatch):
        import asyncio
        start_calls = []
        set_exp_calls = []
        fake = _install_fake_mlflow(monkeypatch, start_calls=start_calls)
        fake.set_experiment = lambda **kw: set_exp_calls.append(kw)

        tracing_fresh._enabled = True

        async def run():
            async with tracing_fresh.start_router_root_span(
                "router.query",
                experiment_id="42",
                router_id="r1",
                span_type="AGENT",
                inputs={"q": "hi"},
                attributes={"router_id": "r1"},
            ):
                assert tracing_fresh.is_router_context_active() is True
                with tracing_fresh.span("gateway.cache.lookup") as cs:
                    cs.set_outputs({"hit": True})
            # contextvar must reset on exit
            assert tracing_fresh.is_router_context_active() is False

        try:
            asyncio.run(run())
        finally:
            tracing_fresh._enabled = False

        assert set_exp_calls == [{"experiment_id": "42"}]
        assert len(start_calls) == 2
        root_kwargs = start_calls[0]
        child_kwargs = start_calls[1]
        assert root_kwargs == {"name": "router.query", "span_type": "AGENT"}
        assert child_kwargs == {"name": "gateway.cache.lookup", "span_type": "CHAIN"}

    def test_root_span_noop_when_experiment_id_none(self, tracing_fresh, monkeypatch):
        import asyncio
        start_calls = []
        set_exp_calls = []
        fake = _install_fake_mlflow(monkeypatch, start_calls=start_calls)
        fake.set_experiment = lambda **kw: set_exp_calls.append(kw)
        tracing_fresh._enabled = True

        async def run():
            async with tracing_fresh.start_router_root_span(
                "router.query",
                experiment_id=None,
                router_id="r1",
            ):
                assert tracing_fresh.is_router_context_active() is False
                with tracing_fresh.span("child"):
                    pass

        try:
            asyncio.run(run())
        finally:
            tracing_fresh._enabled = False
        assert start_calls == []
        assert set_exp_calls == []

    def test_root_span_noop_when_globally_disabled(self, tracing_fresh, monkeypatch):
        import asyncio
        start_calls = []
        _install_fake_mlflow(monkeypatch, start_calls=start_calls)

        async def run():
            async with tracing_fresh.start_router_root_span(
                "router.query",
                experiment_id="42",
                router_id="r1",
            ):
                assert tracing_fresh.is_router_context_active() is False

        asyncio.run(run())
        assert start_calls == []


class TestSpanFailureSafe:
    def test_enabled_span_falls_back_to_noop_on_mlflow_error(self, tracing_fresh, monkeypatch):
        # Set up: enabled, contextvar set, but mlflow.start_span raises.
        _install_fake_mlflow(monkeypatch, raise_on_start=True)
        tracing_fresh._enabled = True
        token = tracing_fresh._router_trace_ctx.set({"experiment_id": "42", "router_id": "r1"})
        try:
            with tracing_fresh.span("test") as s:
                s.set_outputs({"x": 1})
                assert s.trace_id is None
        finally:
            tracing_fresh._router_trace_ctx.reset(token)
            tracing_fresh._enabled = False

    def test_user_body_exception_is_not_swallowed(self, tracing_fresh, monkeypatch):
        """If the user code inside `with tracing.span(...)` raises, the exception
        must propagate to the caller. tracing.span only catches mlflow setup
        errors. This used to be broken — the except wrapped the yield and would
        re-yield a noop, swallowing real bugs (e.g. JSON parse errors)."""
        _install_fake_mlflow(monkeypatch)
        tracing_fresh._enabled = True
        token = tracing_fresh._router_trace_ctx.set({"experiment_id": "42", "router_id": "r1"})
        try:
            with pytest.raises(ValueError, match="boom"):
                with tracing_fresh.span("test"):
                    raise ValueError("boom")
        finally:
            tracing_fresh._router_trace_ctx.reset(token)
            tracing_fresh._enabled = False


class TestExperimentResolution:
    def test_resolve_returns_none_when_disabled(self, tracing_fresh):
        assert tracing_fresh.resolve_experiment_id("/Users/x/exp") is None

    def test_resolve_returns_none_for_falsy_path(self, tracing_fresh):
        tracing_fresh._enabled = True
        try:
            assert tracing_fresh.resolve_experiment_id(None) is None
            assert tracing_fresh.resolve_experiment_id("") is None
        finally:
            tracing_fresh._enabled = False

    def test_resolve_caches_lookup(self, tracing_fresh, monkeypatch):
        fake = _install_fake_mlflow(monkeypatch)

        class _Exp:
            experiment_id = "777"

        calls = []

        class _Client:
            def get_experiment_by_name(self, name):
                calls.append(name)
                return _Exp()

        fake.MlflowClient = lambda: _Client()
        tracing_fresh._enabled = True
        try:
            assert tracing_fresh.resolve_experiment_id("/p") == "777"
            assert tracing_fresh.resolve_experiment_id("/p") == "777"
            assert calls == ["/p"]  # second call cached
        finally:
            tracing_fresh._enabled = False
            tracing_fresh.invalidate_experiment_cache()


class TestEnsureExperiment:
    def test_validates_path_format(self, tracing_fresh, monkeypatch):
        _install_fake_mlflow(monkeypatch)
        with pytest.raises(ValueError):
            tracing_fresh.ensure_experiment("")
        with pytest.raises(ValueError):
            tracing_fresh.ensure_experiment("relative/path")

    def test_returns_existing_id(self, tracing_fresh, monkeypatch):
        fake = _install_fake_mlflow(monkeypatch)

        class _Exp:
            experiment_id = "555"

        class _Client:
            def get_experiment_by_name(self, name):
                return _Exp()

            def create_experiment(self, name):  # pragma: no cover - shouldn't run
                raise AssertionError("should not create when exists")

        fake.MlflowClient = lambda: _Client()
        assert tracing_fresh.ensure_experiment("/Users/x/exp") == "555"

    def test_creates_when_missing(self, tracing_fresh, monkeypatch):
        fake = _install_fake_mlflow(monkeypatch)

        class _Client:
            def get_experiment_by_name(self, name):
                return None

            def create_experiment(self, name):
                return "999"

        fake.MlflowClient = lambda: _Client()
        assert tracing_fresh.ensure_experiment("/Users/x/new") == "999"

    def test_propagates_errors(self, tracing_fresh, monkeypatch):
        fake = _install_fake_mlflow(monkeypatch)

        class _Client:
            def get_experiment_by_name(self, name):
                return None

            def create_experiment(self, name):
                raise RuntimeError("permission denied")

        fake.MlflowClient = lambda: _Client()
        with pytest.raises(RuntimeError):
            tracing_fresh.ensure_experiment("/Users/x/forbidden")
