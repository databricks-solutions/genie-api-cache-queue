"""
Test configuration: sys.path setup and infrastructure stubs.

Heavy third-party dependencies (databricks-sdk, pydantic-settings, asyncpg,
pgvector) and internal infrastructure modules are stubbed out here so that
tests run without any external services or installed packages beyond what
pytest and fastapi require.

Load order matters:
  1. Third-party stubs must be in sys.modules BEFORE any app.* import fires.
  2. Real parent packages (app, app.services, app.api) must be imported FROM
     DISK before registering leaf stubs for their children — otherwise Python
     treats the parent as having an empty __path__ and cannot find siblings.
  3. Every stub module must also be set as an attribute on its parent package
     so that unittest.mock.patch() can resolve dotted paths by walking
     real module attributes (e.g. patch("app.config.get_settings", ...)).
"""
import sys
import os
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# 1. Put backend/ on sys.path so "import app" resolves to backend/app/
# ---------------------------------------------------------------------------
_backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend not in sys.path:
    sys.path.insert(0, _backend)


# ---------------------------------------------------------------------------
# 2. Stub helpers
# ---------------------------------------------------------------------------

def _make_stub(name: str, **attrs) -> types.ModuleType:
    """Create and register a stub module in sys.modules."""
    mod = types.ModuleType(name)
    mod.__path__ = []
    mod.__package__ = name
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def _attach_to_parent(name: str) -> None:
    """Set sys.modules[name] as an attribute on its parent package.
    Required so unittest.mock can resolve dotted patch paths by walking
    module attributes (it calls getattr(parent, child_name)).
    """
    mod = sys.modules[name]
    parent_name, _, child_name = name.rpartition(".")
    if parent_name and parent_name in sys.modules:
        setattr(sys.modules[parent_name], child_name, mod)


# ---------------------------------------------------------------------------
# 3. Third-party stubs — must be registered BEFORE any app.* import fires
# ---------------------------------------------------------------------------

# databricks.sdk — used by app.auth at import time
_make_stub("databricks")
_make_stub("databricks.sdk", WorkspaceClient=MagicMock())
_make_stub("databricks.sdk.core", Config=MagicMock())

# pydantic_settings — used by app.config to define a BaseSettings subclass
_make_stub("pydantic_settings", BaseSettings=object, SettingsConfigDict=MagicMock())

# asyncpg / pgvector — used by storage backends, not the units under test
_make_stub("asyncpg")
_make_stub("pgvector")
_make_stub("pgvector.asyncpg")


# ---------------------------------------------------------------------------
# 4. Stub app.auth, app.config, app.models, app.runtime_config BEFORE
#    importing any real app.* module.  These pull in third-party packages at
#    class-definition time or trigger module-level side-effects we must avoid.
# ---------------------------------------------------------------------------
_make_stub("app")                          # placeholder; overwritten in step 5
_make_stub("app.auth",
           ensure_https=lambda h: h if h.startswith("https://") else f"https://{h}",
           get_service_principal_token=MagicMock(return_value=None))
_make_stub("app.config",
           get_settings=MagicMock(return_value=MagicMock(databricks_host="")))
_make_stub("app.models", RuntimeConfig=MagicMock())
_make_stub("app.runtime_config", RuntimeSettings=MagicMock())


# ---------------------------------------------------------------------------
# 5. Import real parent packages from disk.
#    This overwrites the placeholder stubs with real package objects that have
#    the correct on-disk __path__, so sibling modules (rbac.py, auth_helpers.py)
#    can be found by the import machinery.
#    The imports succeed because all their transitive third-party deps are already
#    stubbed in sys.modules from step 3/4.
# ---------------------------------------------------------------------------
import importlib

# Re-import app from disk (overrides the stub registered in step 4)
del sys.modules["app"]
import app          # noqa: E402

# Now set the leaf stubs we registered in step 4 as attributes on `app` so
# that patch("app.config.get_settings", ...) resolves correctly.
app.auth = sys.modules["app.auth"]
app.config = sys.modules["app.config"]
app.models = sys.modules["app.models"]
app.runtime_config = sys.modules["app.runtime_config"]

import app.services # noqa: E402  — real package from disk
import app.api      # noqa: E402  — real package from disk


# ---------------------------------------------------------------------------
# 6. Leaf stubs for internal modules that must not load for real.
#    Parent packages are real disk packages (step 5), so their siblings
#    remain discoverable.
# ---------------------------------------------------------------------------

# app.api.config_store: get_effective_setting() is called inside require_role
_make_stub("app.api.config_store",
           get_effective_setting=MagicMock(return_value=""))
_attach_to_parent("app.api.config_store")

# app.services.database: resolve_role imports this lazily at call time.
# db_service=None means "no DB configured" — triggers the DEFAULT_ROLE path.
_make_stub("app.services.database", db_service=None)
_attach_to_parent("app.services.database")
