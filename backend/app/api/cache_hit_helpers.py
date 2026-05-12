"""Pure helpers for the cache-hit response path in genie_clone_routes.

Extracted to avoid pulling in fastapi/httpx/SDK transitively when tests want
to exercise the response-shape logic in isolation. No I/O, no global state.

The bug these helpers guard against (see eval/RCA_WRONG_BIND_2026-04-27.md):
when the cached SQL re-execution failed at the warehouse — exception OR
non-SUCCEEDED status — the gateway used to return `status=COMPLETED` with
`row_count=0`. Downstream router DAG binding then surfaced `no_data_array`,
and external callers couldn't distinguish "valid empty answer" from "broken
upstream." Now we surface FAILED with the warehouse error so callers can
react and traces show the real cause.
"""
import uuid

ATT_PREFIX = "acache_"


def classify_cache_hit_exec(sql_result: dict | None) -> dict | None:
    """Translate a `genie_service.execute_sql` result into an `exec_error` dict if
    the warehouse re-execution returned a non-SUCCEEDED status.

    Returns:
        None if `sql_result.status == "SUCCEEDED"` OR if the input is None
        (caller is expected to set exec_error from the exception path).
        Otherwise: `{"error": str, "type": "EXEC_FAILED"}`.
    """
    if not isinstance(sql_result, dict):
        return None
    sql_status = sql_result.get("status")
    if sql_status == "SUCCEEDED":
        return None
    warehouse_err = sql_result.get("error")
    err_msg = warehouse_err if isinstance(warehouse_err, str) else (
        (warehouse_err or {}).get("message") if isinstance(warehouse_err, dict) else None
    )
    return {
        "error": f"Cache hit SQL re-execution {sql_status or 'returned no status'}"
                 + (f": {err_msg}" if err_msg else ""),
        "type": "EXEC_FAILED",
    }


def build_cache_hit_response(
    *,
    sql_query: str,
    sql_result: dict | None,
    exec_error: dict | None,
    conv_id: str,
    msg_id: str,
    att_id: str,
    auth_mode: str,
    text_att_id: str | None = None,
) -> dict:
    """Build the unstripped cache-hit response (with `_proxy`).

    When `exec_error` is set, status=FAILED, top-level `error` is populated, and
    `_proxy.result` stays None — preventing the silent corruption where re-exec
    failures returned status=COMPLETED with row_count=0.
    """
    statement_id = sql_result.get("statement_id") if isinstance(sql_result, dict) else None
    sql_status = sql_result.get("status") if isinstance(sql_result, dict) else None
    row_count = 0
    if isinstance(sql_result, dict) and isinstance(sql_result.get("result"), dict):
        row_count = sql_result["result"].get("row_count", 0)

    final_status = "FAILED" if exec_error else "COMPLETED"
    proxy_stage = "failed" if exec_error else "completed"

    if text_att_id is None:
        text_att_id = f"{ATT_PREFIX}txt_{uuid.uuid4().hex[:16]}"

    response: dict = {
        "conversation_id": conv_id,
        "message_id": msg_id,
        "status": final_status,
        "attachments": [
            {
                "attachment_id": att_id,
                "query": {
                    "query": sql_query,
                    "description": ("Cached query — SQL re-execution FAILED."
                                    if exec_error
                                    else "Cached query — SQL re-executed against warehouse."),
                    **({"statement_id": statement_id} if statement_id else {}),
                    "query_result_metadata": {"row_count": row_count},
                },
            },
            {
                "attachment_id": text_att_id,
                "text": {"content": "This result was served from the semantic cache."},
            },
        ],
    }
    if exec_error:
        response["error"] = exec_error

    actual_result = None
    if sql_status == "SUCCEEDED" and isinstance(sql_result, dict):
        actual_result = sql_result.get("result")

    response["_proxy"] = {
        "stage": proxy_stage,
        "from_cache": True,
        "sql_query": sql_query,
        "result": actual_result,
        "auth_mode": auth_mode,
    }
    return response
