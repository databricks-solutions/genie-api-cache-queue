"""
MLflow tracing wrapper.

All tracing calls in the app go through this module so the on/off gate, the
experiment wiring, and the noop-when-disabled behavior live in one place
instead of being scattered across call sites.

Design notes:
- Gated on TRACING_ENABLED env var. When off, `span()` yields a noop and
  mlflow is never imported. Default off — opt-in.
- Experiment path resolved from MLFLOW_EXPERIMENT_NAME. On Databricks, this
  is a workspace path like `/Shared/genie-gateway-traces`; the experiment
  is auto-created on first `set_experiment` call.
- Async-friendly: MLflow 2.20+ supports async context propagation via
  contextvars — `mlflow.start_span` works inside `async def` the same way it
  works sync.
- `_enabled` is process-global. If init fails we stay disabled and log once;
  we do not try to recover per-call.
"""

import contextlib
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

_enabled = False
_experiment_name: Optional[str] = None


def is_enabled() -> bool:
    return _enabled


def current_experiment() -> Optional[str]:
    return _experiment_name


def _truthy(val: str) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


async def init_tracing() -> None:
    """Initialize MLflow tracing if TRACING_ENABLED=true.

    Safe to call from FastAPI lifespan. Never raises — tracing failure must not
    block app boot.
    """
    global _enabled, _experiment_name

    if not _truthy(os.getenv("TRACING_ENABLED", "")):
        logger.info("Tracing disabled (set TRACING_ENABLED=true to enable)")
        return

    try:
        import mlflow  # noqa: F401
    except ImportError as e:
        logger.warning("Tracing enabled but mlflow import failed: %s", e)
        return

    exp_name = os.getenv("MLFLOW_EXPERIMENT_NAME")
    if not exp_name:
        logger.warning("TRACING_ENABLED is set but MLFLOW_EXPERIMENT_NAME is not — "
                       "tracing will fall back to a local mlruns/ dir which is lost "
                       "on container restart. Set MLFLOW_EXPERIMENT_NAME in app.yaml.")

    try:
        import mlflow
        # Databricks Apps runtime injects SP OAuth creds but does NOT default
        # mlflow.tracking_uri to 'databricks'. Without this, set_experiment +
        # start_span write to a local ./mlruns/ dir that's lost on every
        # container restart. Setting the URI explicitly here routes traces to
        # Databricks Managed MLflow, which is the whole point.
        current_uri = mlflow.get_tracking_uri()
        if not current_uri or "databricks" not in current_uri.lower():
            mlflow.set_tracking_uri("databricks")
            logger.info("Tracing URI set to databricks (was %r)", current_uri)
        # Same story for the registry URI — needed for some trace metadata writes.
        try:
            mlflow.set_registry_uri("databricks")
        except Exception:
            pass
        if exp_name:
            mlflow.set_experiment(exp_name)
            _experiment_name = exp_name
        # Async logging batches span writes off the hot path (~80% overhead reduction)
        try:
            mlflow.config.enable_async_logging()
        except Exception:
            pass
        _enabled = True
        logger.info("Tracing ENABLED (experiment=%s, tracking_uri=%s)",
                    exp_name or "<local mlruns/>", mlflow.get_tracking_uri())
    except Exception as e:
        logger.warning("Tracing init failed: %s — continuing with tracing disabled", e)


class _NoopSpan:
    """No-op stand-in for mlflow.entities.Span when tracing is disabled.

    Matches the methods we actually call. Keeps call-site code branch-free:
    every caller can do `with span(...) as s: s.set_outputs(...)` regardless
    of whether tracing is on.
    """
    trace_id = None

    def set_inputs(self, *args, **kwargs) -> None:
        pass

    def set_outputs(self, *args, **kwargs) -> None:
        pass

    def set_attribute(self, *args, **kwargs) -> None:
        pass

    def set_attributes(self, *args, **kwargs) -> None:
        pass

    def set_status(self, *args, **kwargs) -> None:
        pass


@contextlib.contextmanager
def span(
    name: str,
    *,
    span_type: str = "CHAIN",
    inputs: Any = None,
    attributes: Optional[dict] = None,
):
    """Context manager that opens an MLflow span when tracing is enabled.

    Usage:
        with tracing.span("router.query", span_type="AGENT",
                          inputs={"question": q}, attributes={"router_id": rid}) as s:
            ...
            s.set_outputs({"n_picks": len(picks)})

    When tracing is disabled, yields a _NoopSpan and the `with` block runs
    with zero extra cost (aside from a dict lookup and method dispatch on the
    noop).
    """
    if not _enabled:
        yield _NoopSpan()
        return

    try:
        import mlflow
        # mlflow.start_span only accepts name + span_type as kwargs. Inputs and
        # attributes must be set on the returned span object post-creation.
        with mlflow.start_span(name=name, span_type=span_type) as s:
            if inputs is not None:
                try:
                    s.set_inputs(inputs)
                except Exception:
                    pass
            if attributes:
                for k, v in attributes.items():
                    try:
                        s.set_attribute(k, v)
                    except Exception:
                        pass
            yield s
    except Exception as e:
        # If mlflow blows up mid-request, don't take down the request — log and
        # fall back to a noop. This is rare (usually pool/creds issues).
        logger.warning("Tracing span '%s' failed: %s — falling back to noop for this call", name, e)
        yield _NoopSpan()


def current_trace_id() -> Optional[str]:
    """Return the active trace's trace_id string, or None if no active trace / tracing disabled.

    Routes include this in the response so callers can correlate back to the
    trace in the MLflow UI without guessing.
    """
    if not _enabled:
        return None
    try:
        import mlflow
        # mlflow.get_current_active_span() returns None outside of a `with span(...)` block.
        active = mlflow.get_current_active_span()
        if active is None:
            return None
        return getattr(active, "trace_id", None) or getattr(active, "request_id", None)
    except Exception:
        return None
