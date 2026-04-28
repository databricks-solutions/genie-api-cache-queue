"""Tests for eval/score_routing.py.

Pure-Python module — no backend.app imports — so no stubbing dance needed.
"""
import sys
from pathlib import Path

import pytest

# eval/ isn't a real package on the import path; add the repo root.
_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO))

from eval.score_routing import (  # noqa: E402
    AliasResolver,
    GoldEdge,
    GoldSpec,
    _build_alias_resolver,
    _norm_col,
    _question_picks,
    _resolve_actual_edges,
    _resolve_actual_rooms,
    score_question,
)


# ---- Helpers --------------------------------------------------------------


def _aliases(mapping):
    """Build an AliasResolver from {room: gateway_id} without disk + HTTP."""
    return AliasResolver(forward=dict(mapping),
                         reverse={gid: room for room, gid in mapping.items()})


def _row(qid, idx, pick_id, gw, depends_on="", bind_column="", stage_index=0):
    """Construct a CSV row dict matching run_router_eval.py's schema."""
    return {
        "tier": "6",
        "question_id": str(qid),
        "pick_index": str(idx),
        "pick_id": pick_id,
        "depends_on": depends_on,
        "stage_index": str(stage_index),
        "pick_gateway_id": gw,
        "bind_column": bind_column,
        "n_stages": "2",
        "status": "COMPLETED",
    }


# ---- norm_col + small unit pieces -----------------------------------------


def test_norm_col_strips_punctuation_and_case():
    assert _norm_col("donor_id") == "donorid"
    assert _norm_col("Donor ID") == "donorid"
    assert _norm_col("recipient-country.name") == "recipientcountryname"
    assert _norm_col("") == ""
    assert _norm_col(None) == ""


# ---- score_question — full-criteria pass ----------------------------------


def test_pass_required_rooms_and_edges_and_stages():
    aliases = _aliases({"R3": "gw-donors", "R1": "gw-tf"})
    rows = [
        _row(107, 0, "p0", "gw-donors", stage_index=0),
        _row(107, 1, "p1", "gw-tf", depends_on="p0", bind_column="donor_id", stage_index=1),
    ]
    spec = GoldSpec(
        required_rooms=("R3", "R1"),
        required_edges=(GoldEdge(upstream="R3", downstream="R1",
                                 bind_column=("donorid",)),),
        min_stages=2,
    )
    res = score_question(rows, spec, aliases)
    assert res.status == "pass"
    assert res.rooms_match is True
    assert res.edges_match is True
    assert res.stages_match is True


# ---- missing_room ----------------------------------------------------------


def test_fail_missing_room():
    aliases = _aliases({"R3": "gw-donors", "R1": "gw-tf"})
    rows = [_row(99, 0, "p0", "gw-donors")]  # only R3 picked
    spec = GoldSpec(required_rooms=("R3", "R1"))
    res = score_question(rows, spec, aliases)
    assert res.status == "fail"
    assert res.rooms_match is False
    assert "missing_room: R1" in res.failure_reason


# ---- forbidden_room --------------------------------------------------------


def test_fail_forbidden_room():
    aliases = _aliases({"R1": "gw-tf", "R7": "gw-results"})
    rows = [
        _row(50, 0, "p0", "gw-tf"),
        _row(50, 1, "p1", "gw-results"),
    ]
    spec = GoldSpec(required_rooms=("R1",), forbidden_rooms=("R7",))
    res = score_question(rows, spec, aliases)
    assert res.status == "fail"
    assert "forbidden_room: R7" in res.failure_reason


# ---- bind_column synonyms --------------------------------------------------


def test_pass_bind_column_with_synonym_match():
    """Spec accepts donor_id OR donor; actual is 'Donor ID' (display form)."""
    aliases = _aliases({"R3": "gw-donors", "R1": "gw-tf"})
    rows = [
        _row(115, 0, "p0", "gw-donors"),
        _row(115, 1, "p1", "gw-tf", depends_on="p0", bind_column="Donor ID",
             stage_index=1),
    ]
    spec = GoldSpec(
        required_rooms=("R3", "R1"),
        required_edges=(GoldEdge(upstream="R3", downstream="R1",
                                 bind_column=("donorid", "donor")),),
    )
    res = score_question(rows, spec, aliases)
    assert res.status == "pass"


def test_fail_wrong_bind_column():
    aliases = _aliases({"R5": "gw-disb", "R8": "gw-safe"})
    rows = [
        _row(109, 0, "p0", "gw-disb"),
        _row(109, 1, "p1", "gw-safe", depends_on="p0", bind_column="trust_fund_id",
             stage_index=1),
    ]
    spec = GoldSpec(
        required_rooms=("R5", "R8"),
        required_edges=(GoldEdge(upstream="R5", downstream="R8",
                                 bind_column=("projectid",)),),
    )
    res = score_question(rows, spec, aliases)
    assert res.status == "fail"
    assert "wrong_bind" in res.failure_reason


# ---- missing_edge ----------------------------------------------------------


def test_fail_missing_edge_when_picks_are_parallel():
    """Both rooms present but no dependency edge between them."""
    aliases = _aliases({"R5": "gw-disb", "R8": "gw-safe"})
    rows = [
        _row(109, 0, "p0", "gw-disb"),
        _row(109, 1, "p1", "gw-safe"),  # no depends_on
    ]
    spec = GoldSpec(
        required_rooms=("R5", "R8"),
        required_edges=(GoldEdge(upstream="R5", downstream="R8",
                                 bind_column=("projectid",)),),
    )
    res = score_question(rows, spec, aliases)
    assert res.status == "fail"
    assert "missing_edge" in res.failure_reason


# ---- stages ----------------------------------------------------------------


def test_fail_too_few_stages():
    aliases = _aliases({"R1": "gw-tf"})
    rows = [_row(50, 0, "p0", "gw-tf", stage_index=0)]
    spec = GoldSpec(required_rooms=("R1",), min_stages=2)
    res = score_question(rows, spec, aliases)
    assert res.status == "fail"
    assert "too_few_stages" in res.failure_reason


# ---- no_spec ---------------------------------------------------------------


def test_no_spec_when_gold_is_empty():
    aliases = _aliases({"R1": "gw-tf"})
    rows = [_row(99, 0, "p0", "gw-tf")]
    res = score_question(rows, GoldSpec(), aliases)
    assert res.status == "no_spec"


# ---- alias resolver --------------------------------------------------------


def test_alias_resolver_substring_match(tmp_path):
    members = [
        {"gateway_id": "gw-1", "title": "R1 — Trust Fund Portfolio"},
        {"gateway_id": "gw-2", "title": "R2 — Trust Fund Grants & Disbursements"},
        {"gateway_id": "gw-3", "title": "R3 — Donor Relations"},
    ]
    aliases_file = tmp_path / "aliases.yaml"
    aliases_file.write_text(
        "aliases:\n"
        "  R1: 'Portfolio'\n"           # substring, unique
        "  R3: 'Donor Relations'\n"     # exact title (case-insensitive)
    )
    res = _build_alias_resolver(aliases_file, members)
    assert res.forward == {"R1": "gw-1", "R3": "gw-3"}
    assert res.reverse["gw-1"] == "R1"
    assert res.room_for("gw-1") == "R1"
    assert res.room_for("gw-unknown") == "UNKNOWN"


def test_alias_resolver_aborts_on_ambiguous_substring(tmp_path):
    members = [
        {"gateway_id": "gw-1", "title": "R1 — Trust Fund Portfolio"},
        {"gateway_id": "gw-2", "title": "R2 — Trust Fund Grants"},
    ]
    aliases_file = tmp_path / "aliases.yaml"
    aliases_file.write_text("aliases:\n  R1: 'Trust Fund'\n")  # matches both
    with pytest.raises(SystemExit):
        _build_alias_resolver(aliases_file, members)


def test_alias_resolver_uuid_value(tmp_path):
    uuid = "f90e639c-e12f-447b-b5f3-8cc3c31469bc"
    members = [
        {"gateway_id": uuid, "title": "Anything"},
        {"gateway_id": "different-id", "title": "Other"},
    ]
    aliases_file = tmp_path / "aliases.yaml"
    aliases_file.write_text(f"aliases:\n  R1: {uuid}\n")
    res = _build_alias_resolver(aliases_file, members)
    assert res.forward == {"R1": uuid}


# ---- edge resolution sanity -----------------------------------------------


def test_resolve_actual_edges_handles_fanout():
    """Q117-style: one upstream, two parallel dependents."""
    aliases = _aliases({"R4": "gw-proj", "R6": "gw-proc", "R8": "gw-safe"})
    rows = [
        _row(117, 0, "p0", "gw-proj", stage_index=0),
        _row(117, 1, "p1", "gw-safe", depends_on="p0",
             bind_column="project_id", stage_index=1),
        _row(117, 2, "p2", "gw-proc", depends_on="p0",
             bind_column="project_id", stage_index=1),
    ]
    edges = _resolve_actual_edges(rows, aliases)
    assert ("R4", "R8", "projectid") in edges
    assert ("R4", "R6", "projectid") in edges
    assert len(edges) == 2


def test_question_picks_filters_and_sorts():
    """Rows without pick_id (selector-failed-to-decide rows) are dropped."""
    rows = [
        _row(1, 2, "p2", "gw"),
        _row(1, 0, "p0", "gw"),
        _row(1, 1, "", "", ),  # no pick_id — empty fallback row
        _row(1, 1, "p1", "gw"),
    ]
    out = _question_picks(rows)
    assert [r["pick_id"] for r in out] == ["p0", "p1", "p2"]
