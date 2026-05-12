"""
MLflow tracing wrapper — per-router, contextvar-gated.

All tracing calls in the app go through this module so the on/off gate, the
per-router experiment selection, and the noop-when-disabled behavior live in
one place instead of being scattered across call sites.

Design notes:
- Tracing is gated by TRACING_ENABLED + a request-scoped ContextVar set only
  inside a router-fronted request. Direct gateway calls (no router) never set
  the contextvar, so child `span()` calls are no-ops there. This guarantees
  zero traces for gateway-only callers.
- Each router can configure its own MLflow experiment path. On router save we
  resolve-or-create it and cache the experiment_id. At request time we briefly
  acquire a process-wide asyncio.Lock, call `mlflow.set_experiment(experiment_id=...)`,
  open the root span, then release. The lock is held for ~ms while opening the
  root span; child spans run in parallel without contention. After the root is
  open, any concurrent `set_experiment` from another request can't repaint the
  trace — the experiment is captured at root-span creation time.
- Async-friendly: MLflow uses contextvars internally for the active span.
  `mlflow.start_span` works inside `async def` and across `asyncio.create_task`
  (so cache-miss background spans attach to the same trace as the parent).
- We do NOT use `trace_destination=` because older MLflow versions (incl. the
  one the Databricks Apps runtime resolves with `mlflow[databricks]>=2.20.0`)
  don't expose `mlflow.entities.trace_location`, AND `trace_destination` does
  not push the new span onto the active-span context — child spans become
  orphan roots of their own traces.
- `_enabled` is process-global (TRACING_ENABLED). If init fails we stay
  disabled and log once; we do not try to recover per-call.
- Exception handling: only mlflow setup errors are caught and downgraded to
  noop. User-body exceptions inside `with tracing.span(...)` propagate
  normally — otherwise we'd silently swallow real bugs (e.g. JSON parse
  errors in cache validators).
"""

import asyncio
import contextlib
import contextvars
import logging
import os
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)

_enabled = False

# (path → experiment_id). Populated lazily from resolve_experiment_id() and
# eagerly from ensure_experiment(). Negative results are not cached so the
# next request can retry if a path is created out-of-band.
_exp_id_cache: dict[str, str] = {}

# Request-scoped tracing context. Set ONLY by start_router_root_span when a
# router-fronted request opens its root span. `tracing.span()` no-ops unless
# this is set, which keeps direct gateway calls from emitting any spans.
_router_trace_ctx: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "router_trace_ctx", default=None
)

# Serialize the brief (set_experiment → start_span) pair so concurrent router
# requests targeting different experiments don't race the global active
# experiment. Held for milliseconds; child spans run without it.
_root_open_lock: asyncio.Lock = asyncio.Lock()


def is_enabled() -> bool:
    return _enabled


def is_router_context_active() -> bool:
    """True iff we're inside a router-fronted request that opened a root span."""
    return _router_trace_ctx.get() is not None


def _truthy(val: str) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


async def init_tracing() -> None:
    """Initialize MLflow tracing if TRACING_ENABLED=true.

    Only wires the tracking URI + async logging flag; does NOT pin a global
    experiment (each router selects its own at request time). Safe to call
    from FastAPI lifespan; never raises.
    """
    global _enabled

    if not _truthy(os.getenv("TRACING_ENABLED", "")):
        logger.info("Tracing disabled (set TRACING_ENABLED=true to enable)")
        return

    try:
        import mlflow  # noqa: F401
    except ImportError as e:
        logger.warning("Tracing enabled but mlflow import failed: %s", e)
        return

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
        try:
            mlflow.set_registry_uri("databricks")
        except Exception:
            pass
        # Async logging batches span writes off the hot path (~80% overhead reduction)
        try:
            mlflow.config.enable_async_logging()
        except Exception:
            pass
        _enabled = True
        logger.info("Tracing ENABLED (per-router experiments; tracking_uri=%s)",
                    mlflow.get_tracking_uri())
    except Exception as e:
        logger.warning("Tracing init failed: %s — continuing with tracing disabled", e)


class _NoopSpan:
    """No-op stand-in for mlflow.entities.Span when tracing is disabled."""
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


def _apply_inputs_attrs(s, inputs, attributes):
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


@contextlib.asynccontextmanager
async def start_router_root_span(
    name: str,
    *,
    experiment_id: Optional[str],
    router_id: Optional[str] = None,
    span_type: str = "AGENT",
    inputs: Any = None,
    attributes: Optional[dict] = None,
):
    """Open the root span for a router-fronted request.

    Yields a noop and skips the contextvar when `experiment_id is None` or
    tracing is globally disabled — so child spans below stay no-op too.

    Otherwise, briefly acquires `_root_open_lock`, calls
    `mlflow.set_experiment(experiment_id=...)`, opens the root span, then
    releases the lock. The root span captures the experiment at creation time;
    child spans run in parallel without the lock.
    """
    if not _enabled or not experiment_id:
        yield _NoopSpan()
        return

    cm = None
    root = None
    try:
        import mlflow
        async with _root_open_lock:
            try:
                mlflow.set_experiment(experiment_id=str(experiment_id))
            except Exception as e:
                logger.warning("set_experiment(%s) failed: %s", experiment_id, e)
                yield _NoopSpan()
                return
            try:
                cm = mlflow.start_span(name=name, span_type=span_type)
                root = cm.__enter__()
            except Exception as e:
                logger.warning("Tracing root span '%s' failed to open: %s — falling back to noop", name, e)
                cm = None
                yield _NoopSpan()
                return
    except Exception as e:
        # mlflow import or other catastrophic failure — never let tracing block a request.
        logger.warning("Tracing setup failed for '%s': %s", name, e)
        yield _NoopSpan()
        return

    # Root open. Set our contextvar so child tracing.span() calls activate.
    token = _router_trace_ctx.set({
        "experiment_id": str(experiment_id),
        "router_id": router_id,
    })
    _apply_inputs_attrs(root, inputs, attributes)

    exc_info: tuple = (None, None, None)
    try:
        yield root
    except BaseException:
        exc_info = sys.exc_info()
        raise
    finally:
        _router_trace_ctx.reset(token)
        try:
            cm.__exit__(*exc_info)
        except Exception:
            pass


@contextlib.contextmanager
def span(
    name: str,
    *,
    span_type: str = "CHAIN",
    inputs: Any = None,
    attributes: Optional[dict] = None,
):
    """Context manager that opens an MLflow child span when we're inside a
    router-fronted trace.

    No-op if (a) tracing is globally disabled, OR (b) the request did not go
    through a router (no contextvar set). Only mlflow setup errors are caught
    and downgraded; user-body exceptions propagate normally.
    """
    if not _enabled or _router_trace_ctx.get() is None:
        yield _NoopSpan()
        return

    cm = None
    s = None
    try:
        import mlflow
        cm = mlflow.start_span(name=name, span_type=span_type)
        s = cm.__enter__()
    except Exception as e:
        logger.warning("Tracing span '%s' failed to open: %s — falling back to noop", name, e)
        yield _NoopSpan()
        return

    _apply_inputs_attrs(s, inputs, attributes)

    exc_info: tuple = (None, None, None)
    try:
        yield s
    except BaseException:
        exc_info = sys.exc_info()
        raise
    finally:
        try:
            cm.__exit__(*exc_info)
        except Exception:
            pass


def current_trace_id() -> Optional[str]:
    """Return the active trace's trace_id string, or None if none / disabled."""
    if not _enabled:
        return None
    try:
        import mlflow
        active = mlflow.get_current_active_span()
        if active is None:
            return None
        return getattr(active, "trace_id", None) or getattr(active, "request_id", None)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Experiment lookup / create
# ---------------------------------------------------------------------------


def _validate_experiment_path(path: str) -> str:
    """Trim and validate an MLflow workspace experiment path.

    Raises ValueError on bad input; returns the cleaned path.
    """
    if path is None:
        raise ValueError("Experiment path is required")
    cleaned = path.strip()
    if not cleaned:
        raise ValueError("Experiment path cannot be empty")
    if not cleaned.startswith("/"):
        raise ValueError("Experiment path must be a workspace path starting with '/'")
    return cleaned


def resolve_experiment_id(path: Optional[str]) -> Optional[str]:
    """Resolve an experiment path to an id, using an in-process cache.

    Returns None if `path` is falsy, tracing is disabled, or the lookup fails.
    Designed to be called on every router request — failure must NOT raise.
    """
    if not path or not _enabled:
        return None
    cached = _exp_id_cache.get(path)
    if cached:
        return cached
    try:
        import mlflow
        client = mlflow.MlflowClient()
        exp = client.get_experiment_by_name(path)
        if exp is not None:
            _exp_id_cache[path] = exp.experiment_id
            return exp.experiment_id
    except Exception as e:
        logger.warning("Failed to resolve MLflow experiment '%s': %s", path, e)
    return None


def ensure_experiment(path: str) -> str:
    """Get-or-create a workspace experiment by path, return its id.

    Raises on failure. The app SP is the calling principal; when it creates
    an experiment it becomes the owner automatically. When the experiment
    already exists and is owned by another principal, the SP needs CAN_EDIT
    — left to the workspace operator.
    """
    cleaned = _validate_experiment_path(path)
    try:
        import mlflow
    except ImportError as e:
        raise RuntimeError(f"mlflow is not installed: {e}")

    try:
        current_uri = mlflow.get_tracking_uri()
        if not current_uri or "databricks" not in current_uri.lower():
            mlflow.set_tracking_uri("databricks")
    except Exception:
        pass

    client = mlflow.MlflowClient()
    exp = client.get_experiment_by_name(cleaned)
    if exp is not None:
        _exp_id_cache[cleaned] = exp.experiment_id
        return exp.experiment_id

    try:
        exp_id = client.create_experiment(cleaned)
    except Exception as e:
        # Race: another caller may have created it between get and create.
        exp = client.get_experiment_by_name(cleaned)
        if exp is not None:
            _exp_id_cache[cleaned] = exp.experiment_id
            return exp.experiment_id
        raise RuntimeError(f"Failed to create experiment '{cleaned}': {e}")

    _exp_id_cache[cleaned] = exp_id
    logger.info("Created MLflow experiment '%s' (id=%s)", cleaned, exp_id)
    return exp_id


def invalidate_experiment_cache(path: Optional[str] = None) -> None:
    """Drop a single path (or all) from the resolve cache. Used on router
    update when the path changes."""
    if path is None:
        _exp_id_cache.clear()
    else:
        _exp_id_cache.pop(path, None)
