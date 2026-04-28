"""Tests for the heuristic cache-write validator.

The validator runs at cache MISS time (after warehouse exec, before persisting
into pgvector) and decides whether the freshly-produced (question, SQL, result)
triple is good enough to serve to future callers.
"""
from app.services.cache_write_validator import (
    evaluate_cache_write,
    _extract_requested_target,
    _split_targets,
    _REFUSAL_RE,
)


# ──────────────────────────────────────────────────────────────────────────────
# evaluate_cache_write — first failing heuristic wins
# ──────────────────────────────────────────────────────────────────────────────

def test_writes_when_everything_looks_clean():
    d = evaluate_cache_write(
        question="How much did each donor contribute last year?",
        sql_query="SELECT donor_id, SUM(amount) FROM grants GROUP BY donor_id",
        row_count=42,
        columns=["donor_id", "amount_usd"],
        genie_text="Here is a breakdown by donor.",
    )
    assert d.should_write is True
    assert d.reason is None


def test_skips_on_empty_result():
    d = evaluate_cache_write(
        question="who funded x",
        sql_query="SELECT * FROM grants WHERE donor='x'",
        row_count=0,
        columns=["donor_id"],
        genie_text=None,
    )
    assert d.should_write is False
    assert d.reason == "empty_result"


def test_skips_on_genie_refusal_text():
    d = evaluate_cache_write(
        question="forecast revenue 2030",
        sql_query="SELECT 1",
        row_count=5,
        columns=["x"],
        genie_text="I'm sorry, I can't answer that based on the data available.",
    )
    assert d.should_write is False
    assert d.reason == "genie_refusal"


def test_metric_view_sql_is_cached():
    # Regression: MEASURE()/DIMENSION() in cached SQL is fine — UC metric views
    # are queryable from any SQL warehouse on Preview channel / DBR 16.4+ via
    # /api/2.0/sql/statements. Earlier versions of this validator wrongly
    # skipped any SQL containing MEASURE/DIMENSION; that rule was removed.
    d = evaluate_cache_write(
        question="top recipient countries by total grant commitment",
        sql_query=(
            "SELECT `Recipient Country`, MEASURE(`Total Grant Commitment USD`) "
            "FROM mv_tf_execution GROUP BY ALL"
        ),
        row_count=5,
        columns=["Recipient Country", "Total Grant Commitment USD"],
        genie_text=None,
    )
    assert d.should_write is True
    assert d.reason is None


def test_column_mismatch_skips_when_target_explicitly_named():
    d = evaluate_cache_write(
        question="List ONLY the donor_id",
        sql_query="SELECT donor_name FROM grants",
        row_count=5,
        columns=["donor_name", "amount_usd"],
        genie_text=None,
    )
    assert d.should_write is False
    assert d.reason == "column_mismatch"
    assert "donor_id" in (d.detail or "")


def test_column_match_passes_via_fuzzy_stem():
    # "donor_id" stem matches "Donor" display column.
    d = evaluate_cache_write(
        question="List only the donor_id",
        sql_query="SELECT donor_id",
        row_count=5,
        columns=["Donor", "donor_count"],
        genie_text=None,
    )
    assert d.should_write is True


def test_compound_targets_pass_when_all_present():
    # The 2026-04-28 false positive: "List ONLY the X and Y" with both columns
    # present should NOT be skipped. Previous behaviour treated "X and Y" as
    # one compound target and rejected the cache write.
    d = evaluate_cache_write(
        question="List ONLY the trust_fund_id and primary_theme for trust funds funded by donors D",
        sql_query="SELECT trust_fund_id, primary_theme FROM mv",
        row_count=12,
        columns=["trust_fund_id", "primary_theme"],
        genie_text=None,
    )
    assert d.should_write is True


def test_compound_targets_pass_when_at_least_one_present():
    # Generous fallback: if the user names two columns and only one shows up,
    # we still write the cache. Strict interpretation would reject; we prefer
    # cache hits over correctness here because the binder upstream re-validates.
    d = evaluate_cache_write(
        question="List only the donor_id and donor_region",
        sql_query="SELECT donor_id FROM g",
        row_count=5,
        columns=["donor_id"],
        genie_text=None,
    )
    assert d.should_write is True


def test_compound_targets_skipped_when_none_present():
    d = evaluate_cache_write(
        question="List only the donor_id and project_id",
        sql_query="SELECT something_else FROM x",
        row_count=5,
        columns=["unrelated_col"],
        genie_text=None,
    )
    assert d.should_write is False
    assert d.reason == "column_mismatch"


def test_compound_targets_comma_separated():
    d = evaluate_cache_write(
        question="List ONLY the donor_id, project_id, region",
        sql_query="SELECT region FROM x",
        row_count=5,
        columns=["region", "amount"],
        genie_text=None,
    )
    assert d.should_write is True


def test_compound_targets_ampersand():
    d = evaluate_cache_write(
        question="Return just the donor_id & project_id",
        sql_query="SELECT donor_id FROM x",
        row_count=5,
        columns=["donor_id"],
        genie_text=None,
    )
    assert d.should_write is True


def test_column_mismatch_skipped_when_question_has_no_target():
    # No "list only X" pattern → skip the column heuristic, rely on row_count.
    d = evaluate_cache_write(
        question="How much did each donor contribute?",
        sql_query="SELECT donor_id, amount FROM g",
        row_count=5,
        columns=["whatever"],
        genie_text=None,
    )
    assert d.should_write is True


def test_disabled_toggle_always_writes():
    d = evaluate_cache_write(
        question="List only the donor_id",
        sql_query="",
        row_count=0,
        columns=None,
        genie_text="I'm sorry I can't answer.",
        enabled=False,
    )
    assert d.should_write is True
    assert d.reason is None


def test_first_failing_heuristic_wins_empty_beats_refusal():
    # Both empty AND refusal-text — the empty_result reason should be
    # surfaced first because it's checked first.
    d = evaluate_cache_write(
        question="x",
        sql_query="SELECT 1",
        row_count=0,
        columns=["x"],
        genie_text="I'm sorry, no data found",
    )
    assert d.reason == "empty_result"


def test_validator_fails_open_on_unexpected_input():
    # Pass garbage — the validator must NOT raise; it should let the write happen.
    d = evaluate_cache_write(
        question=None,  # type: ignore[arg-type]
        sql_query=123,  # type: ignore[arg-type]
        row_count="not-an-int",  # type: ignore[arg-type]
        columns="not-a-list",  # type: ignore[arg-type]
        genie_text=None,
    )
    assert d.should_write is True


# ──────────────────────────────────────────────────────────────────────────────
# _extract_requested_target — the question-parsing heuristic
# ──────────────────────────────────────────────────────────────────────────────

def test_extract_target_list_only_the_X():
    assert _extract_requested_target("List ONLY the donor_id") == "donor_id"


def test_extract_target_return_just_the_X():
    assert _extract_requested_target("return just the trust_fund_name for each row") == "trust_fund_name"


def test_extract_target_show_the_X_column():
    # "show the donor_id column" — the trailing "column" word should be stripped.
    assert _extract_requested_target("show the donor_id column") == "donor_id"


def test_extract_target_returns_none_for_freeform():
    assert _extract_requested_target("How many donors are there?") is None
    assert _extract_requested_target("Total grant commitments by year") is None


# ──────────────────────────────────────────────────────────────────────────────
# _split_targets — compound-target breakdown
# ──────────────────────────────────────────────────────────────────────────────

def test_split_targets_and_separator():
    assert _split_targets("trust_fund_id and primary_theme") == ["trust_fund_id", "primary_theme"]


def test_split_targets_comma_separator():
    assert _split_targets("donor_id, project_id, region") == ["donor_id", "project_id", "region"]


def test_split_targets_ampersand_separator():
    assert _split_targets("donor_id & project_id") == ["donor_id", "project_id"]
    assert _split_targets("donor_id&project_id") == ["donor_id", "project_id"]


def test_split_targets_or_and_plus():
    assert _split_targets("X or Y") == ["X", "Y"]
    assert _split_targets("X plus Y") == ["X", "Y"]


def test_split_targets_preserves_underscored_names_with_embedded_and():
    # `command_id` / `random_value` MUST NOT split on the embedded "and" / "or"
    # — splitter requires whitespace boundaries.
    assert _split_targets("command_id") == ["command_id"]
    assert _split_targets("random_value") == ["random_value"]
    assert _split_targets("brand_name") == ["brand_name"]


def test_split_targets_single_target_unchanged():
    assert _split_targets("donor_id") == ["donor_id"]


def test_split_targets_empty_or_whitespace():
    assert _split_targets("") == []
    assert _split_targets("   ") == []
    assert _split_targets(None) == []  # type: ignore[arg-type]


def test_split_targets_drops_empty_segments():
    # Trailing comma or doubled separator should not produce empty entries.
    assert _split_targets("donor_id,") == ["donor_id"]
    assert _split_targets("donor_id,, project_id") == ["donor_id", "project_id"]


# ──────────────────────────────────────────────────────────────────────────────
# Pattern-level sanity on the regexes themselves
# ──────────────────────────────────────────────────────────────────────────────

def test_refusal_pattern_matches_common_phrasings():
    assert _REFUSAL_RE.search("I cannot answer this question with the available data.")
    assert _REFUSAL_RE.search("I'm sorry, no records matching that query.")
    assert _REFUSAL_RE.search("Couldn't find any records.")
    assert _REFUSAL_RE.search("This metric is not defined in this space.")
    # Benign summary text should NOT trigger a refusal hit.
    assert not _REFUSAL_RE.search("Here is the breakdown of grants by year.")


