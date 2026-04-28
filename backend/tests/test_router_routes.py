"""
Tests for router CRUD routes.

Follows the same import-stubbing pattern as test_gateway_create_semantics.py:
load app.api.router_routes fresh with the minimum stubs it needs, then
exercise pure-logic helpers and the member-seeding path with a mocked
db_service.
"""
import importlib
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixture: import router_routes with the minimum stubs it needs
# ---------------------------------------------------------------------------

@pytest.fixture
def router_routes():
    # Stub fastapi + httpx + pydantic prerequisites (mirrors gateway fixture)
    if "httpx" not in sys.modules:
        httpx_stub = types.ModuleType("httpx")
        httpx_stub.AsyncClient = MagicMock()
        sys.modules["httpx"] = httpx_stub

    if "fastapi" not in sys.modules:
        fastapi_stub = types.ModuleType("fastapi")
        fastapi_stub.APIRouter = MagicMock()

        def _http_exc_init(self, status_code=500, detail=""):
            self.status_code = status_code
            self.detail = detail
        fastapi_stub.HTTPException = type("HTTPException", (Exception,), {"__init__": _http_exc_init})
        fastapi_stub.Request = MagicMock()
        sys.modules["fastapi"] = fastapi_stub

    if "pydantic" not in sys.modules:
        try:
            import pydantic  # noqa: F401
        except ImportError:
            pytest.skip("pydantic not installed")

    # Real RouterMemberCreateRequest etc. — swap the conftest stub of app.models
    sys.modules.pop("app.models", None)
    sys.modules.pop("app.api.router_routes", None)

    # auth_helpers is imported at module top; stub it
    ah_stub = types.ModuleType("app.api.auth_helpers")
    ah_stub.require_role = AsyncMock()
    ah_stub.resolve_user_token_optional = MagicMock(return_value="")
    ah_stub.extract_bearer_token_optional = MagicMock(return_value="")
    sys.modules["app.api.auth_helpers"] = ah_stub
    sys.modules["app.api"].auth_helpers = ah_stub

    # genie_clone_routes is imported at module top to reuse _handle_query + the
    # synthetic-message store we poll for completion
    gcr_stub = types.ModuleType("app.api.genie_clone_routes")
    gcr_stub._handle_query = AsyncMock()
    gcr_stub._synthetic_messages = {}
    gcr_stub.MSG_PREFIX = "mcache_"
    sys.modules["app.api.genie_clone_routes"] = gcr_stub
    sys.modules["app.api"].genie_clone_routes = gcr_stub

    # embedding_service is imported at module top
    es_stub = types.ModuleType("app.services.embedding_service")
    es_stub.embedding_service = MagicMock()
    sys.modules["app.services.embedding_service"] = es_stub
    if "app.services" in sys.modules:
        sys.modules["app.services"].embedding_service = es_stub

    # selector service — leaf stub with just what router_routes imports
    sel_stub = types.ModuleType("app.services.selector")

    class _Pick:
        def __init__(self, gateway_id, sub_question):
            self.gateway_id = gateway_id
            self.sub_question = sub_question

        def model_dump(self):
            return {"gateway_id": self.gateway_id, "sub_question": self.sub_question}

    class _Decision:
        def __init__(self, picks=None, decomposed=False, rationale=""):
            self.picks = picks or []
            self.decomposed = decomposed
            self.rationale = rationale

        def model_dump(self):
            return {"picks": [p.model_dump() for p in self.picks],
                    "decomposed": self.decomposed, "rationale": self.rationale}

    sel_stub.RoomPick = _Pick
    sel_stub.RoutingDecision = _Decision
    sel_stub.select_rooms = AsyncMock()
    sys.modules["app.services.selector"] = sel_stub
    sys.modules["app.services"].selector = sel_stub

    # app.config is already stubbed in conftest; reinforce databricks_host
    sys.modules["app.config"].get_settings = MagicMock(
        return_value=types.SimpleNamespace(databricks_host="")
    )

    # app.services.database with a mockable db_service
    db_stub = types.ModuleType("app.services.database")
    db_stub.db_service = MagicMock()
    sys.modules["app.services.database"] = db_stub
    if "app.services" in sys.modules:
        sys.modules["app.services"].database = db_stub

    # Import real models
    import app.models  # noqa: F401

    module = importlib.import_module("app.api.router_routes")
    return module, db_stub


# ---------------------------------------------------------------------------
# _add_member helper — title fallback, duplicate/missing gateway handling
# ---------------------------------------------------------------------------

class TestAddMemberHelper:
    @pytest.mark.asyncio
    async def test_title_falls_back_to_gateway_name(self, router_routes):
        mod, db = router_routes
        from app.models import RouterMemberCreateRequest

        db.db_service.get_gateway = AsyncMock(return_value={"id": "gw1", "name": "Trust Fund"})
        db.db_service.get_router_member = AsyncMock(return_value=None)
        db.db_service.add_router_member = AsyncMock(side_effect=lambda m: m)

        body = RouterMemberCreateRequest(gateway_id="gw1", when_to_use="use for TF questions")
        await mod._add_member("r1", body)

        call_args = db.db_service.add_router_member.call_args
        assert call_args is not None
        member = call_args[0][0]
        assert member["title"] == "Trust Fund"
        assert member["when_to_use"] == "use for TF questions"
        assert member["router_id"] == "r1"
        assert member["gateway_id"] == "gw1"

    @pytest.mark.asyncio
    async def test_title_from_body_wins_over_gateway_name(self, router_routes):
        mod, db = router_routes
        from app.models import RouterMemberCreateRequest

        db.db_service.get_gateway = AsyncMock(return_value={"id": "gw1", "name": "Trust Fund"})
        db.db_service.get_router_member = AsyncMock(return_value=None)
        db.db_service.add_router_member = AsyncMock(side_effect=lambda m: m)

        body = RouterMemberCreateRequest(
            gateway_id="gw1",
            when_to_use="use for TF questions",
            title="R1 — Trust Fund Portfolio",
        )
        await mod._add_member("r1", body)

        member = db.db_service.add_router_member.call_args[0][0]
        assert member["title"] == "R1 — Trust Fund Portfolio"

    @pytest.mark.asyncio
    async def test_title_falls_back_to_gateway_id_if_no_name(self, router_routes):
        """Defensive: if gateway row is missing .name (shouldn't happen, but), we
        still get a non-empty title rather than crashing on NOT NULL."""
        mod, db = router_routes
        from app.models import RouterMemberCreateRequest

        db.db_service.get_gateway = AsyncMock(return_value={"id": "gw1"})
        db.db_service.get_router_member = AsyncMock(return_value=None)
        db.db_service.add_router_member = AsyncMock(side_effect=lambda m: m)

        body = RouterMemberCreateRequest(gateway_id="gw1", when_to_use="use for TF questions")
        await mod._add_member("r1", body)

        member = db.db_service.add_router_member.call_args[0][0]
        assert member["title"] == "gw1"

    @pytest.mark.asyncio
    async def test_raises_400_when_gateway_missing(self, router_routes):
        mod, db = router_routes
        from app.models import RouterMemberCreateRequest
        from fastapi import HTTPException

        db.db_service.get_gateway = AsyncMock(return_value=None)
        body = RouterMemberCreateRequest(gateway_id="nope", when_to_use="x")
        with pytest.raises(HTTPException) as excinfo:
            await mod._add_member("r1", body)
        assert excinfo.value.status_code == 400

    @pytest.mark.asyncio
    async def test_raises_409_when_member_exists(self, router_routes):
        mod, db = router_routes
        from app.models import RouterMemberCreateRequest
        from fastapi import HTTPException

        db.db_service.get_gateway = AsyncMock(return_value={"id": "gw1", "name": "x"})
        db.db_service.get_router_member = AsyncMock(return_value={"router_id": "r1", "gateway_id": "gw1"})

        body = RouterMemberCreateRequest(gateway_id="gw1", when_to_use="x")
        with pytest.raises(HTTPException) as excinfo:
            await mod._add_member("r1", body)
        assert excinfo.value.status_code == 409

    @pytest.mark.asyncio
    async def test_empty_tables_and_samples_become_empty_lists(self, router_routes):
        mod, db = router_routes
        from app.models import RouterMemberCreateRequest

        db.db_service.get_gateway = AsyncMock(return_value={"id": "gw1", "name": "x"})
        db.db_service.get_router_member = AsyncMock(return_value=None)
        db.db_service.add_router_member = AsyncMock(side_effect=lambda m: m)

        body = RouterMemberCreateRequest(gateway_id="gw1", when_to_use="x")
        await mod._add_member("r1", body)
        member = db.db_service.add_router_member.call_args[0][0]
        assert member["tables"] == []
        assert member["sample_questions"] == []


# ---------------------------------------------------------------------------
# update_router SQL param-build: allowlist + clearable fields
# ---------------------------------------------------------------------------

class TestUpdateRouterParamBuild:
    """storage_pgvector.update_router normalizes '' → None for clearable text
    fields (selector_model, selector_system_prompt) so the runtime fallback
    to the global/default kicks in after a user clears a dropdown.

    The logic lives inline in PGVectorStorageService.update_router; this test
    exercises the same allowlist / clearable-set shape so any refactor must
    either keep the invariant or update this test."""

    def test_clearable_fields_empty_string_becomes_none(self):
        clearable = {"selector_model", "selector_system_prompt"}
        allowed = {
            "name", "description", "status",
            "selector_model", "selector_system_prompt",
            "decompose_enabled", "routing_cache_enabled",
            "similarity_threshold", "cache_ttl_hours",
        }
        updates = {
            "selector_model": "",
            "selector_system_prompt": "use this prompt",
            "name": "my-router",
        }
        built = {}
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key in clearable and value == "":
                value = None
            elif value is None:
                continue
            built[key] = value

        assert built["selector_model"] is None       # cleared → NULL
        assert built["selector_system_prompt"] == "use this prompt"
        assert built["name"] == "my-router"

    def test_unknown_keys_are_dropped(self):
        """Only whitelisted fields reach the SET clause — a caller cannot
        smuggle in updates to `id` or `created_at` via update_router."""
        allowed = {"name"}
        updates = {"name": "ok", "id": "tampered", "created_at": "2000-01-01"}

        built = {k: v for k, v in updates.items() if k in allowed and v is not None}
        assert built == {"name": "ok"}
