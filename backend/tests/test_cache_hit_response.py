"""Tests for the cache-hit response builder + warehouse-status classifier.

The bug these test guards against: pre-fix, when `genie_service.execute_sql`
raised an exception OR returned a non-SUCCEEDED status during cache-hit
re-execution, the gateway swallowed the failure and returned
`status=COMPLETED` with `row_count=0`. Downstream router DAG binding then
surfaced `no_data_array`, and external callers couldn't tell "empty answer"
from "broken upstream." See eval/RCA_WRONG_BIND_2026-04-27.md.

The helpers under test are pure (no I/O, no fastapi). Tests import them
directly from `app.api.cache_hit_helpers`.
"""
from app.api.cache_hit_helpers import (
    build_cache_hit_response,
    classify_cache_hit_exec,
)


# ---- classify_cache_hit_exec ---------------------------------------------


def test_classify_succeeded_returns_none():
    sql_result = {"status": "SUCCEEDED", "result": {"data_array": [], "row_count": 0}}
    assert classify_cache_hit_exec(sql_result) is None


def test_classify_failed_returns_exec_failed_with_message():
    sql_result = {
        "status": "FAILED",
        "error": {"message": "PARSE_SYNTAX_ERROR: unexpected token at line 3"},
    }
    err = classify_cache_hit_exec(sql_result)
    assert err is not None
    assert err["type"] == "EXEC_FAILED"
    assert "FAILED" in err["error"]
    assert "PARSE_SYNTAX_ERROR" in err["error"]


def test_classify_handles_string_error():
    sql_result = {"status": "CANCELED", "error": "user cancelled"}
    err = classify_cache_hit_exec(sql_result)
    assert err["type"] == "EXEC_FAILED"
    assert "CANCELED" in err["error"]
    assert "user cancelled" in err["error"]


def test_classify_handles_no_status():
    err = classify_cache_hit_exec({})
    assert err["type"] == "EXEC_FAILED"
    assert "no status" in err["error"]


def test_classify_returns_none_for_none_input():
    """Caller already sets exec_error from the exception path; None means 'no opinion'."""
    assert classify_cache_hit_exec(None) is None


# ---- build_cache_hit_response — success path -----------------------------


def test_build_response_succeeded_populates_proxy_result():
    sql_result = {
        "status": "SUCCEEDED",
        "statement_id": "stmt-123",
        "result": {
            "columns": ["donor_id"],
            "data_array": [["d1"], ["d2"]],
            "row_count": 2,
        },
    }
    resp = build_cache_hit_response(
        sql_query="SELECT donor_id FROM t",
        sql_result=sql_result,
        exec_error=None,
        conv_id="ccache_x", msg_id="mcache_x", att_id="att_x",
        auth_mode="user",
        text_att_id="att_text_x",
    )
    assert resp["status"] == "COMPLETED"
    assert "error" not in resp
    assert resp["_proxy"]["stage"] == "completed"
    assert resp["_proxy"]["from_cache"] is True
    assert resp["_proxy"]["result"]["row_count"] == 2
    assert resp["_proxy"]["result"]["data_array"] == [["d1"], ["d2"]]
    att_q = resp["attachments"][0]["query"]
    assert att_q["statement_id"] == "stmt-123"
    assert att_q["query_result_metadata"]["row_count"] == 2
    assert "FAILED" not in att_q["description"]


# ---- build_cache_hit_response — failure paths ----------------------------


def test_build_response_exec_exception_marks_failed():
    """Pre-fix this returned COMPLETED + row_count=0 — the silent corruption."""
    exec_error = {"error": "Cache hit SQL execution failed: Connection reset",
                  "type": "EXEC_EXCEPTION"}
    resp = build_cache_hit_response(
        sql_query="SELECT 1",
        sql_result=None,
        exec_error=exec_error,
        conv_id="c", msg_id="m", att_id="a",
        auth_mode="user",
    )
    assert resp["status"] == "FAILED"
    assert resp["error"] == exec_error
    assert resp["_proxy"]["stage"] == "failed"
    assert resp["_proxy"]["result"] is None
    assert resp["_proxy"]["from_cache"] is True   # still WAS a cache hit attempt
    assert "FAILED" in resp["attachments"][0]["query"]["description"]


def test_build_response_warehouse_failed_marks_failed():
    """Generic warehouse-FAILED path: any non-SUCCEEDED status surfaces as FAILED."""
    sql_result = {
        "status": "FAILED",
        "statement_id": "stmt-bad",
        "error": {"message": "PARSE_SYNTAX_ERROR: unexpected token"},
        "result": None,
    }
    exec_error = classify_cache_hit_exec(sql_result)
    resp = build_cache_hit_response(
        sql_query="SELECT bogus FROM t",
        sql_result=sql_result,
        exec_error=exec_error,
        conv_id="c", msg_id="m", att_id="a",
        auth_mode="user",
    )
    assert resp["status"] == "FAILED"
    assert "PARSE_SYNTAX_ERROR" in resp["error"]["error"]
    assert resp["_proxy"]["result"] is None
    assert resp["_proxy"]["stage"] == "failed"


def test_build_response_temporarily_unavailable_marks_failed():
    """Q116 case: warehouse INLINE-disposition concurrency throttle."""
    sql_result = {
        "status": "FAILED",
        "statement_id": None,
        "error": {"message": "Too many concurrent requests for disposition INLINE."},
    }
    exec_error = classify_cache_hit_exec(sql_result)
    resp = build_cache_hit_response(
        sql_query="SELECT 1",
        sql_result=sql_result,
        exec_error=exec_error,
        conv_id="c", msg_id="m", att_id="a",
        auth_mode="user",
    )
    assert resp["status"] == "FAILED"
    assert "INLINE" in resp["error"]["error"]
    assert resp["_proxy"]["result"] is None


def test_build_response_succeeded_with_zero_rows_stays_completed():
    """Genuine empty result is COMPLETED, not FAILED — important to keep."""
    sql_result = {
        "status": "SUCCEEDED",
        "statement_id": "stmt-empty",
        "result": {"columns": ["x"], "data_array": [], "row_count": 0},
    }
    resp = build_cache_hit_response(
        sql_query="SELECT 1 WHERE 1=0",
        sql_result=sql_result,
        exec_error=None,
        conv_id="c", msg_id="m", att_id="a",
        auth_mode="user",
    )
    assert resp["status"] == "COMPLETED"
    assert resp["_proxy"]["stage"] == "completed"
    assert resp["_proxy"]["result"] == {"columns": ["x"], "data_array": [], "row_count": 0}


def test_build_response_attachments_always_include_cache_marker():
    """The 'served from semantic cache' text attachment is preserved on FAILED."""
    resp = build_cache_hit_response(
        sql_query="SELECT 1",
        sql_result=None,
        exec_error={"error": "boom", "type": "EXEC_EXCEPTION"},
        conv_id="c", msg_id="m", att_id="a",
        auth_mode="user",
        text_att_id="att_text",
    )
    text_atts = [a for a in resp["attachments"] if "text" in a]
    assert len(text_atts) == 1
    assert "semantic cache" in text_atts[0]["text"]["content"].lower()
