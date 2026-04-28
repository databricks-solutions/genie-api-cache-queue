"""
Tests for the Route-A DAG scheduler and binding helpers in router_routes.

Unlike test_router_routes.py which stubs the selector with a minimal _Pick,
these tests load the REAL selector.RoomPick dataclass so we can exercise
depends_on / bind / id fields end-to-end. The router_routes module is loaded
with its dependencies (httpx, fastapi, genie_clone_routes, embedding_service,
database) stubbed but `selector` left real.
"""
import importlib
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def dag_module():
    """Import router_routes with REAL selector, stubbed everything else."""
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

    # Ensure databricks.sdk.core is present — real selector imports Config from it.
    if "databricks.sdk.core" not in sys.modules:
        core_stub = types.ModuleType("databricks.sdk.core")
        core_stub.Config = MagicMock()
        sys.modules["databricks.sdk.core"] = core_stub
        sys.modules["databricks.sdk"].core = core_stub

    # Drop any prior stubs so we get real selector + real router_routes.
    sys.modules.pop("app.models", None)
    sys.modules.pop("app.api.router_routes", None)
    sys.modules.pop("app.services.selector", None)

    # Stub upstream router_routes deps (genie_clone_routes, embedding_service,
    # database, auth_helpers) — they're irrelevant for DAG pure-helper tests.
    ah_stub = types.ModuleType("app.api.auth_helpers")
    ah_stub.require_role = AsyncMock()
    ah_stub.resolve_user_token_optional = MagicMock(return_value="")
    ah_stub.extract_bearer_token_optional = MagicMock(return_value="")
    sys.modules["app.api.auth_helpers"] = ah_stub
    sys.modules["app.api"].auth_helpers = ah_stub

    gcr_stub = types.ModuleType("app.api.genie_clone_routes")
    gcr_stub._handle_query = AsyncMock()
    gcr_stub._synthetic_messages = {}
    gcr_stub.MSG_PREFIX = "mcache_"
    sys.modules["app.api.genie_clone_routes"] = gcr_stub
    sys.modules["app.api"].genie_clone_routes = gcr_stub

    es_stub = types.ModuleType("app.services.embedding_service")
    es_stub.embedding_service = MagicMock()
    sys.modules["app.services.embedding_service"] = es_stub
    if "app.services" in sys.modules:
        sys.modules["app.services"].embedding_service = es_stub

    sys.modules["app.config"].get_settings = MagicMock(
        return_value=types.SimpleNamespace(databricks_host="")
    )

    db_stub = types.ModuleType("app.services.database")
    db_stub.db_service = MagicMock()
    sys.modules["app.services.database"] = db_stub
    if "app.services" in sys.modules:
        sys.modules["app.services"].database = db_stub

    # Real models + real selector
    import app.models  # noqa: F401
    import app.services.selector as real_selector  # noqa: F401

    module = importlib.import_module("app.api.router_routes")
    return module, real_selector


# ---------------------------------------------------------------------------
# _topological_stages
# ---------------------------------------------------------------------------

class TestTopologicalStages:
    def test_empty_picks_returns_empty(self, dag_module):
        mod, _ = dag_module
        assert mod._topological_stages([]) == []

    def test_single_pick_one_stage(self, dag_module):
        mod, sel = dag_module
        p = sel.RoomPick(id="p0", gateway_id="gw1", sub_question="q")
        stages = mod._topological_stages([p])
        assert len(stages) == 1
        assert stages[0] == [p]

    def test_two_independent_picks_one_stage(self, dag_module):
        mod, sel = dag_module
        p0 = sel.RoomPick(id="p0", gateway_id="gw1", sub_question="q0")
        p1 = sel.RoomPick(id="p1", gateway_id="gw2", sub_question="q1")
        stages = mod._topological_stages([p0, p1])
        assert len(stages) == 1
        assert {p.id for p in stages[0]} == {"p0", "p1"}

    def test_two_stage_chain(self, dag_module):
        mod, sel = dag_module
        p0 = sel.RoomPick(id="p0", gateway_id="gw1", sub_question="q0")
        p1 = sel.RoomPick(id="p1", gateway_id="gw2", sub_question="q1", depends_on=["p0"])
        stages = mod._topological_stages([p0, p1])
        assert [[p.id for p in s] for s in stages] == [["p0"], ["p1"]]

    def test_three_stage_chain(self, dag_module):
        mod, sel = dag_module
        p0 = sel.RoomPick(id="p0", gateway_id="gw1", sub_question="q0")
        p1 = sel.RoomPick(id="p1", gateway_id="gw2", sub_question="q1", depends_on=["p0"])
        p2 = sel.RoomPick(id="p2", gateway_id="gw3", sub_question="q2", depends_on=["p1"])
        stages = mod._topological_stages([p0, p1, p2])
        assert [[p.id for p in s] for s in stages] == [["p0"], ["p1"], ["p2"]]

    def test_diamond_dependencies(self, dag_module):
        # p0 → {p1, p2} → p3
        mod, sel = dag_module
        p0 = sel.RoomPick(id="p0", gateway_id="gw1", sub_question="q0")
        p1 = sel.RoomPick(id="p1", gateway_id="gw2", sub_question="q1", depends_on=["p0"])
        p2 = sel.RoomPick(id="p2", gateway_id="gw3", sub_question="q2", depends_on=["p0"])
        p3 = sel.RoomPick(id="p3", gateway_id="gw4", sub_question="q3", depends_on=["p1", "p2"])
        stages = mod._topological_stages([p0, p1, p2, p3])
        assert len(stages) == 3
        assert [p.id for p in stages[0]] == ["p0"]
        assert {p.id for p in stages[1]} == {"p1", "p2"}
        assert [p.id for p in stages[2]] == ["p3"]

    def test_cycle_flattens_gracefully(self, dag_module):
        # Selector output with a circular ref; scheduler should not loop forever.
        mod, sel = dag_module
        p0 = sel.RoomPick(id="p0", gateway_id="gw1", sub_question="q0", depends_on=["p1"])
        p1 = sel.RoomPick(id="p1", gateway_id="gw2", sub_question="q1", depends_on=["p0"])
        stages = mod._topological_stages([p0, p1])
        # Collapse to single stage with deps stripped.
        assert len(stages) == 1
        assert {p.id for p in stages[0]} == {"p0", "p1"}
        for p in stages[0]:
            assert p.depends_on == []


# ---------------------------------------------------------------------------
# _extract_bound_values
# ---------------------------------------------------------------------------

def _result_with_schema(columns: list[str], rows: list[list]) -> dict:
    return {
        "result": {
            "schema": {"columns": [{"name": c} for c in columns]},
            "data_array": rows,
        }
    }


class TestExtractBoundValues:
    def test_column_by_name(self, dag_module):
        mod, _ = dag_module
        resp = _result_with_schema(["donor_id", "pledge"], [[1, 100], [2, 200], [3, 300]])
        values, reason = mod._extract_bound_values(resp, "donor_id", "list")
        assert values == ["1", "2", "3"]
        assert reason == ""

    def test_case_insensitive_column_match(self, dag_module):
        mod, _ = dag_module
        resp = _result_with_schema(["Donor_ID", "pledge"], [[1, 100], [2, 200]])
        values, reason = mod._extract_bound_values(resp, "donor_id", "list")
        assert values == ["1", "2"]
        assert reason == ""

    def test_single_column_fallback(self, dag_module):
        mod, _ = dag_module
        # Upstream returned one column "id" but selector asked for "donor_id".
        resp = _result_with_schema(["id"], [[10], [20], [30]])
        values, reason = mod._extract_bound_values(resp, "donor_id", "list")
        assert values == ["10", "20", "30"]
        assert reason == ""

    def test_column_not_found_multi_column(self, dag_module):
        mod, _ = dag_module
        resp = _result_with_schema(["foo", "bar"], [[1, 2], [3, 4]])
        values, reason = mod._extract_bound_values(resp, "donor_id", "list")
        assert values == []
        assert reason == "column_not_found"

    def test_empty_upstream(self, dag_module):
        mod, _ = dag_module
        resp = _result_with_schema(["donor_id"], [])
        values, reason = mod._extract_bound_values(resp, "donor_id", "list")
        assert values == []
        assert reason == "upstream_empty"

    def test_deduplicates_preserving_order(self, dag_module):
        mod, _ = dag_module
        resp = _result_with_schema(["donor_id"], [[1], [2], [1], [3], [2]])
        values, reason = mod._extract_bound_values(resp, "donor_id", "list")
        assert values == ["1", "2", "3"]
        assert reason == ""

    def test_scalar_reducer_stops_at_first(self, dag_module):
        mod, _ = dag_module
        resp = _result_with_schema(["donor_id"], [[1], [2], [3]])
        values, reason = mod._extract_bound_values(resp, "donor_id", "scalar")
        assert values == ["1"]
        assert reason == ""

    def test_caps_at_200(self, dag_module):
        mod, _ = dag_module
        rows = [[i] for i in range(500)]
        resp = _result_with_schema(["donor_id"], rows)
        values, _ = mod._extract_bound_values(resp, "donor_id", "list")
        assert len(values) == 200

    def test_no_data_array(self, dag_module):
        mod, _ = dag_module
        values, reason = mod._extract_bound_values({}, "donor_id", "list")
        assert values == []
        assert reason == "no_data_array"

    def test_extracts_from_proxy_result(self, dag_module):
        """Router-internal path: rows live on response._proxy.result, not .result."""
        mod, _ = dag_module
        proxy_resp = {
            "status": "COMPLETED",
            "_proxy": {
                "result": {
                    "schema": {"columns": [{"name": "donor_id"}]},
                    "data_array": [[7], [8], [9]],
                },
            },
        }
        values, reason = mod._extract_bound_values(proxy_resp, "donor_id", "list")
        assert reason == ""
        assert values == ["7", "8", "9"]

    def test_flat_columns_shape(self, dag_module):
        """Prod shape: result.columns is a flat list of strings."""
        mod, _ = dag_module
        resp = {
            "_proxy": {
                "result": {
                    "columns": ["project_id", "amount"],
                    "data_array": [["P1", 1], ["P2", 2]],
                },
            },
        }
        values, reason = mod._extract_bound_values(resp, "project_id", "list")
        assert reason == ""
        assert values == ["P1", "P2"]

    def test_fuzzy_id_suffix_strip(self, dag_module):
        """Selector said 'project_id' but room returned display name 'Project'."""
        mod, _ = dag_module
        resp = {
            "_proxy": {
                "result": {
                    "columns": ["Project", "net_disbursement_usd"],
                    "data_array": [["P003358", "1.82e10"], ["P011090", "1.49e10"]],
                },
            },
        }
        values, reason = mod._extract_bound_values(resp, "project_id", "list")
        assert reason == ""
        assert values == ["P003358", "P011090"]

    def test_fuzzy_substring_donor(self, dag_module):
        """Selector said 'donor_id' but result column is 'Donor'."""
        mod, _ = dag_module
        resp = {"_proxy": {"result": {"columns": ["Donor"], "data_array": [[1], [2]]}}}
        values, reason = mod._extract_bound_values(resp, "donor_id", "list")
        assert reason == ""
        assert values == ["1", "2"]

    def test_fuzzy_rejects_metric_suffix(self, dag_module):
        """`trust_fund_id` must NOT match `trust_fund_count` (aggregate column)."""
        mod, _ = dag_module
        resp = {
            "_proxy": {
                "result": {
                    "columns": ["theme_name", "trust_fund_count"],
                    "data_array": [["Climate", 30], ["Health", 20]],
                },
            },
        }
        values, reason = mod._extract_bound_values(resp, "trust_fund_id", "list")
        assert reason == "column_not_found"
        assert values == []

    def test_fuzzy_handles_spaced_display_name(self, dag_module):
        """`trust_fund_id` matches `Trust Fund` (space-separated display label)."""
        mod, _ = dag_module
        resp = {
            "_proxy": {
                "result": {
                    "columns": ["Trust Fund", "disbursement_ratio"],
                    "data_array": [["TF402", 0.5], ["TF377", 0.7]],
                },
            },
        }
        values, reason = mod._extract_bound_values(resp, "trust_fund_id", "list")
        assert reason == ""
        assert values == ["TF402", "TF377"]

    def test_fuzzy_strips_name_suffix(self, dag_module):
        """`recipient_country_name` matches `Recipient Country` (name suffix stripped)."""
        mod, _ = dag_module
        resp = {
            "_proxy": {
                "result": {
                    "columns": ["Recipient Country", "total_grant_commitment_usd"],
                    "data_array": [["YEM", 1e8], ["UKR", 5e7]],
                },
            },
        }
        values, reason = mod._extract_bound_values(resp, "recipient_country_name", "list")
        assert reason == ""
        assert values == ["YEM", "UKR"]

    def test_fuzzy_strips_ids_plural(self, dag_module):
        """`project_ids` (plural) matches `Project`."""
        mod, _ = dag_module
        resp = {"_proxy": {"result": {"columns": ["Project"], "data_array": [["P1"], ["P2"]]}}}
        values, reason = mod._extract_bound_values(resp, "project_ids", "list")
        assert reason == ""
        assert values == ["P1", "P2"]


# ---------------------------------------------------------------------------
# _render_sub_question
# ---------------------------------------------------------------------------

class TestRenderSubQuestion:
    def test_no_bind_passes_through(self, dag_module):
        mod, sel = dag_module
        p = sel.RoomPick(id="p0", gateway_id="gw1", sub_question="plain question")
        rendered, diag = mod._render_sub_question(p, {})
        assert rendered == "plain question"
        assert diag == {}

    def test_happy_path_substitution(self, dag_module):
        mod, sel = dag_module
        p0_result = {
            "status": "COMPLETED",
            "response": _result_with_schema(["donor_id"], [[1], [2], [3]]),
        }
        p = sel.RoomPick(
            id="p1", gateway_id="gw1",
            sub_question="Show gift history for donors {{donor_ids}}.",
            depends_on=["p0"],
            bind=[{"placeholder": "donor_ids", "upstream": "p0",
                   "column": "donor_id", "reducer": "list"}],
        )
        rendered, diag = mod._render_sub_question(p, {"p0": p0_result})
        assert rendered == "Show gift history for donors 1, 2, 3."
        assert diag["donor_ids"]["n_values"] == 3
        assert diag["donor_ids"]["sample_values"] == ["1", "2", "3"]

    def test_upstream_missing_fails(self, dag_module):
        mod, sel = dag_module
        p = sel.RoomPick(
            id="p1", gateway_id="gw1", sub_question="{{x}}",
            depends_on=["p0"],
            bind=[{"placeholder": "x", "upstream": "p0", "column": "c", "reducer": "list"}],
        )
        rendered, diag = mod._render_sub_question(p, {})
        assert rendered is None
        assert diag["failure_reason"] == "upstream_missing"

    def test_upstream_failed_status(self, dag_module):
        mod, sel = dag_module
        failed = {"status": "FAILED", "response": {}}
        p = sel.RoomPick(
            id="p1", gateway_id="gw1", sub_question="{{x}}",
            depends_on=["p0"],
            bind=[{"placeholder": "x", "upstream": "p0", "column": "c", "reducer": "list"}],
        )
        rendered, diag = mod._render_sub_question(p, {"p0": failed})
        assert rendered is None
        assert diag["failure_reason"] == "upstream_failed"

    def test_column_not_found(self, dag_module):
        mod, sel = dag_module
        upstream = {
            "status": "COMPLETED",
            "response": _result_with_schema(["a", "b"], [[1, 2]]),
        }
        p = sel.RoomPick(
            id="p1", gateway_id="gw1", sub_question="{{x}}",
            depends_on=["p0"],
            bind=[{"placeholder": "x", "upstream": "p0", "column": "donor_id", "reducer": "list"}],
        )
        rendered, diag = mod._render_sub_question(p, {"p0": upstream})
        assert rendered is None
        assert diag["failure_reason"] == "column_not_found"

    def test_multi_bind_all_resolve(self, dag_module):
        mod, sel = dag_module
        p0_result = {"status": "COMPLETED", "response": _result_with_schema(["x"], [[1]])}
        p1_result = {"status": "COMPLETED", "response": _result_with_schema(["y"], [["a"], ["b"]])}
        p = sel.RoomPick(
            id="p2", gateway_id="gw", sub_question="x={{x}} y={{y}}",
            depends_on=["p0", "p1"],
            bind=[
                {"placeholder": "x", "upstream": "p0", "column": "x", "reducer": "list"},
                {"placeholder": "y", "upstream": "p1", "column": "y", "reducer": "list"},
            ],
        )
        rendered, _ = mod._render_sub_question(p, {"p0": p0_result, "p1": p1_result})
        assert rendered == "x=1 y=a, b"


# ---------------------------------------------------------------------------
# Selector pick parser (depends_on / bind normalization)
# ---------------------------------------------------------------------------

class TestSelectorParsePicks:
    def test_synthesizes_missing_ids(self, dag_module):
        _, sel = dag_module
        active = [{"gateway_id": "gw1"}, {"gateway_id": "gw2"}]
        raw = [
            {"gateway_id": "gw1", "sub_question": "q0"},
            {"gateway_id": "gw2", "sub_question": "q1"},
        ]
        picks = sel._parse_picks(raw, active)
        assert [p.id for p in picks] == ["p0", "p1"]
        assert all(p.depends_on == [] and p.bind == [] for p in picks)

    def test_drops_unknown_upstream(self, dag_module):
        _, sel = dag_module
        active = [{"gateway_id": "gw1"}, {"gateway_id": "gw2"}]
        raw = [
            {"id": "a", "gateway_id": "gw1", "sub_question": "q0"},
            {"id": "b", "gateway_id": "gw2", "sub_question": "q1",
             "depends_on": ["a", "ghost"]},
        ]
        picks = sel._parse_picks(raw, active)
        assert picks[1].depends_on == ["a"]

    def test_placeholder_bind_mismatch_strips_deps(self, dag_module):
        _, sel = dag_module
        active = [{"gateway_id": "gw1"}, {"gateway_id": "gw2"}]
        raw = [
            {"id": "p0", "gateway_id": "gw1", "sub_question": "q0"},
            # sub_question has no {{x}}, but bind says it does → mismatch
            {"id": "p1", "gateway_id": "gw2", "sub_question": "plain q1",
             "depends_on": ["p0"],
             "bind": [{"placeholder": "x", "upstream": "p0",
                       "column": "c", "reducer": "list"}]},
        ]
        picks = sel._parse_picks(raw, active)
        assert picks[1].depends_on == []
        assert picks[1].bind == []
        # sub_question preserved so the pick still runs (unbound).
        assert picks[1].sub_question == "plain q1"

    def test_drops_picks_with_unknown_gateway(self, dag_module):
        _, sel = dag_module
        active = [{"gateway_id": "gw1"}]
        raw = [
            {"gateway_id": "gw1", "sub_question": "q0"},
            {"gateway_id": "ghost", "sub_question": "q1"},
        ]
        picks = sel._parse_picks(raw, active)
        assert [p.gateway_id for p in picks] == ["gw1"]

    def test_bind_upstream_must_be_in_depends_on(self, dag_module):
        _, sel = dag_module
        active = [{"gateway_id": "gw1"}, {"gateway_id": "gw2"}]
        raw = [
            {"id": "p0", "gateway_id": "gw1", "sub_question": "q0"},
            # bind.upstream="ghost" — not in depends_on, must be dropped
            {"id": "p1", "gateway_id": "gw2", "sub_question": "q1 {{x}}",
             "depends_on": ["p0"],
             "bind": [{"placeholder": "x", "upstream": "ghost",
                       "column": "c", "reducer": "list"}]},
        ]
        picks = sel._parse_picks(raw, active)
        # Bind entry dropped → placeholder in sub_question with no bind → mismatch → strip deps
        assert picks[1].bind == []
        assert picks[1].depends_on == []


# ---------------------------------------------------------------------------
# _execute_dag — dispatcher end-to-end with stubbed gateway
# ---------------------------------------------------------------------------

def _mk_gw_response(sql: str, columns: list[str], rows: list[list], msg_id: str = "mcache_abc") -> dict:
    return {
        "conversation_id": "ccache_abc",
        "message_id": msg_id,
        "status": "COMPLETED",
        "attachments": [{"query": {"query": sql,
                                    "query_result_metadata": {"row_count": len(rows)}}}],
        "result": {
            "schema": {"columns": [{"name": c} for c in columns]},
            "data_array": rows,
            "row_count": len(rows),
        },
    }


class TestExecuteDag:
    @pytest.mark.asyncio
    async def test_parallel_flat_plan_dispatches_once_per_pick(self, dag_module, monkeypatch):
        mod, sel = dag_module

        async def fake_get_gateway(gateway_id):
            return {"id": gateway_id, "genie_space_id": f"space_{gateway_id}"}

        calls = []

        async def fake_handle_query(space_id, query_text, token, identity, gateway, auth_mode):
            calls.append((space_id, query_text))
            return _mk_gw_response(
                sql=f"SELECT * FROM {space_id}",
                columns=["id"],
                rows=[[1]],
            )

        monkeypatch.setattr(mod._db.db_service, "get_gateway", fake_get_gateway)
        monkeypatch.setattr(mod, "_gateway_handle_query", fake_handle_query)
        # Short-circuit _poll_for_completion — we return COMPLETED synchronously
        async def fake_poll(msg_id, timeout_s=1.0):
            return {"status": "COMPLETED"}
        monkeypatch.setattr(mod, "_poll_for_completion", fake_poll)

        picks = [
            sel.RoomPick(id="p0", gateway_id="gw1", sub_question="qA"),
            sel.RoomPick(id="p1", gateway_id="gw2", sub_question="qB"),
        ]
        sources, stats = await mod._execute_dag(picks, token="tok", identity="u")
        assert stats["n_stages"] == 1
        assert len(sources) == 2
        assert {s["pick_id"] for s in sources} == {"p0", "p1"}
        assert all(s["status"] == "COMPLETED" for s in sources)
        assert {c[1] for c in calls} == {"qA", "qB"}

    @pytest.mark.asyncio
    async def test_two_stage_chain_binds_upstream_values(self, dag_module, monkeypatch):
        mod, sel = dag_module

        async def fake_get_gateway(gateway_id):
            return {"id": gateway_id, "genie_space_id": f"space_{gateway_id}"}

        calls: list[tuple] = []

        async def fake_handle_query(space_id, query_text, token, identity, gateway, auth_mode):
            calls.append((space_id, query_text))
            if "gw_up" in space_id:
                return _mk_gw_response("SELECT donor_id FROM donors", ["donor_id"], [[1], [2], [3]])
            return _mk_gw_response("SELECT * FROM dependent", ["col"], [["ok"]])

        monkeypatch.setattr(mod._db.db_service, "get_gateway", fake_get_gateway)
        monkeypatch.setattr(mod, "_gateway_handle_query", fake_handle_query)
        async def fake_poll(msg_id, timeout_s=1.0):
            return {"status": "COMPLETED"}
        monkeypatch.setattr(mod, "_poll_for_completion", fake_poll)

        picks = [
            sel.RoomPick(id="p0", gateway_id="gw_up", sub_question="Find donors."),
            sel.RoomPick(
                id="p1", gateway_id="gw_down",
                sub_question="Show gift history for donors {{donor_ids}}.",
                depends_on=["p0"],
                bind=[{"placeholder": "donor_ids", "upstream": "p0",
                       "column": "donor_id", "reducer": "list"}],
            ),
        ]
        sources, stats = await mod._execute_dag(picks, token="tok", identity="u")
        assert stats["n_stages"] == 2

        # Second dispatch must have the bound donor ids substituted in.
        dependent_calls = [q for sp, q in calls if sp == "space_gw_down"]
        assert dependent_calls == ["Show gift history for donors 1, 2, 3."]
        # Sources should carry the bound sub_question for the dependent pick.
        p1_source = next(s for s in sources if s["pick_id"] == "p1")
        assert p1_source["bound_sub_question"] == "Show gift history for donors 1, 2, 3."
        assert p1_source["stage_index"] == 1

    @pytest.mark.asyncio
    async def test_dependent_pick_skipped_on_upstream_failure(self, dag_module, monkeypatch):
        mod, sel = dag_module

        async def fake_get_gateway(gateway_id):
            return {"id": gateway_id, "genie_space_id": f"space_{gateway_id}"}

        async def fake_handle_query(space_id, query_text, token, identity, gateway, auth_mode):
            # Upstream fails.
            return {
                "status": "FAILED", "message_id": "mcache_f",
                "attachments": [], "error": {"error": "boom"},
            }

        monkeypatch.setattr(mod._db.db_service, "get_gateway", fake_get_gateway)
        monkeypatch.setattr(mod, "_gateway_handle_query", fake_handle_query)
        async def fake_poll(msg_id, timeout_s=1.0):
            return {"status": "FAILED", "error": {"error": "boom"}}
        monkeypatch.setattr(mod, "_poll_for_completion", fake_poll)

        picks = [
            sel.RoomPick(id="p0", gateway_id="gw_up", sub_question="Find ids."),
            sel.RoomPick(
                id="p1", gateway_id="gw_down",
                sub_question="{{ids}}", depends_on=["p0"],
                bind=[{"placeholder": "ids", "upstream": "p0",
                       "column": "id", "reducer": "list"}],
            ),
        ]
        sources, stats = await mod._execute_dag(picks, token="tok", identity="u")
        assert stats["n_skipped_upstream_failed"] == 1
        p1_source = next(s for s in sources if s["pick_id"] == "p1")
        assert p1_source["status"] == "SKIPPED"
        assert p1_source["error"] == "upstream_failed"
