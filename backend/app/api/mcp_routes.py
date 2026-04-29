"""
MCP (Model Context Protocol) server — drop-in replacement for the Databricks
managed Genie MCP endpoint.

Clients point to this server instead of the workspace MCP endpoint.  Same
JSON-RPC protocol, same tool names (parameterized by space_id/gateway_id),
same input/output schemas.  Transparent semantic caching and rate-limit
queue underneath.

Endpoint:
  POST /api/2.0/mcp/genie/{space_id}   — Streamable HTTP (JSON-RPC 2.0)
"""

import json
import logging
import uuid
import asyncio
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.auth import ensure_https
from app.config import get_settings
from app.api.auth_helpers import extract_bearer_token
from app.api.config_store import get_effective_setting
from app.services.embedding_service import embedding_service
from app.services.genie_service import genie_service, GenieRateLimitError
from app.services.intent_splitter import split_by_intent
from app.services.question_normalizer import normalize_question
from app.services.cache_validator import validate_cache_entry
from app.services.prompt_enricher import get_space_context
from app.services.rate_limiter import get_rate_limiter as _get_rate_limiter
import app.services.database as _db

_rate_limiter = _get_rate_limiter()
_poll_locks: dict[str, asyncio.Lock] = {}

logger = logging.getLogger(__name__)
settings = get_settings()

mcp_router = APIRouter()

# In-memory store shared with clone routes for background query state
from app.api.genie_clone_routes import (
    _synthetic_messages,
    CONV_PREFIX,
    MSG_PREFIX,
    ATT_PREFIX,
    _resolve_gateway_space_id,
    _build_runtime_settings,
    _make_synthetic_ids,
    _process_genie_background,
)

# Router-MCP reuses the routing-decision + DAG-execution path from REST so the
# MCP handler is a thin protocol adapter, not a second copy of the logic.
from app.api.router_routes import _resolve_decision, _execute_dag
from app.api.auth_helpers import require_role, resolve_user_token_optional
from app.services import tracing

# ── Protocol constants ────────────────────────────────────────────────
PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "GenieCacheQueueMCP"
SERVER_VERSION = "1.0.0"


# ── Helpers ───────────────────────────────────────────────────────────

def _jsonrpc_ok(req_id, result: dict):
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


def _jsonrpc_error(req_id, code: int, message: str, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": err})


async def _fetch_space_metadata(space_id: str, token: str) -> dict:
    """Fetch Genie space title and description from the real API."""
    host = ensure_https(settings.databricks_host)
    url = f"{host}/api/2.0/genie/spaces/{space_id}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=15.0)
            if resp.is_success:
                return resp.json()
    except Exception as e:
        logger.warning("Failed to fetch space metadata for %s: %s", space_id, e)
    return {}


async def _execute_sql_raw(sql_query: str, rs) -> dict:
    """Execute SQL and return the raw SQL Statement API response.

    The managed MCP returns the full ``statement_response`` object inside
    ``queryAttachments``.  Our existing ``genie_service.execute_sql`` strips
    the raw response, so we call the SQL Statement API directly here.
    """
    host = ensure_https(rs.databricks_host)
    url = f"{host}/api/2.0/sql/statements"
    headers = {
        "Authorization": f"Bearer {rs.databricks_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers=headers,
            json={
                "statement": sql_query,
                "warehouse_id": rs.sql_warehouse_id,
                "wait_timeout": "30s",
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()

        statement_id = data.get("statement_id")
        status = data.get("status", {}).get("state")

        if status not in ("SUCCEEDED", "FAILED", "CANCELED"):
            for _ in range(30):
                await asyncio.sleep(1)
                poll = await client.get(
                    f"{host}/api/2.0/sql/statements/{statement_id}",
                    headers=headers,
                    timeout=30.0,
                )
                poll.raise_for_status()
                data = poll.json()
                if data.get("status", {}).get("state") in ("SUCCEEDED", "FAILED", "CANCELED"):
                    break

        return data


def _build_structured_content(
    status: str,
    conversation_id: str,
    message_id: str,
    query_attachments: list | None = None,
    text_attachments: list | None = None,
    suggested_questions: list | None = None,
) -> dict:
    return {
        "content": {
            "queryAttachments": query_attachments or [],
            "textAttachments": text_attachments or [],
            "suggestedQuestions": suggested_questions or [],
        },
        "conversationId": conversation_id,
        "messageId": message_id,
        "status": status,
    }


def _wrap_tool_result(structured: dict, is_error: bool = False) -> dict:
    """Wrap structured content into the MCP tools/call result envelope."""
    return {
        "content": [{"type": "text", "text": json.dumps(structured)}],
        "isError": is_error,
        "structuredContent": structured,
    }


# ── Tool schemas (generated per space_id) ────────────────────────────

def _build_tools(space_id: str, title: str, description: str) -> list:
    desc_line = f"Genie Space description: {description}" if description else ""
    return [
        {
            "name": f"query_space_{space_id}",
            "description": (
                f"Query the {title} genie space for data insights.\n"
                "You can ask natural language questions and will receive responses "
                "in natural language or as SQL query results.\n"
                "You can ask for a summary of the datasets in the genie space to "
                "get an overview of the data available.\n"
                "By default, each query is standalone. Optionally, provide a "
                "conversation_id to continue an existing conversation.\n"
                "If you do not have a conversation_id, please provide all relevant "
                "context in the query.\n"
                "The response will include the conversation_id, message_id, and "
                "status of the message in the genie space.\n"
                "If the message is not complete, use "
                f"poll_response_{space_id} with the returned conversation_id "
                "and message_id to poll until the message reaches a completed state.\n"
                f"The genie space description is as follows:\n{desc_line}"
            ),
            "inputSchema": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Query for genie space",
                    },
                    "conversation_id": {
                        "type": "string",
                        "description": "Optional conversation ID to continue an existing conversation",
                    },
                },
            },
            "outputSchema": _output_schema(),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": f"poll_response_{space_id}",
            "description": (
                f"Poll for the response of a previously initiated message in the "
                f"{title} genie space.\n"
                "Use this tool to retrieve results for a message that was started "
                "but not yet completed.\n"
                "Requires both conversation_id and message_id returned from the "
                f"initial query_space_{space_id} tool call.\n"
                "Please continue polling with this tool until the message reaches "
                "a completed state."
            ),
            "inputSchema": {
                "type": "object",
                "required": ["conversation_id", "message_id"],
                "properties": {
                    "conversation_id": {
                        "type": "string",
                        "description": "The conversation ID from the genie space",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "The message ID to poll for the response of",
                    },
                },
            },
            "outputSchema": _output_schema(),
            "annotations": {"readOnlyHint": True},
        },
    ]


def _output_schema() -> dict:
    return {
        "type": "object",
        "required": ["content", "conversationId", "messageId", "status"],
        "properties": {
            "content": {
                "type": "object",
                "properties": {
                    "queryAttachments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "description": {"type": "string"},
                                "statement_response": {},
                            },
                        },
                    },
                    "textAttachments": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "suggestedQuestions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
            "conversationId": {"type": "string"},
            "messageId": {"type": "string"},
            "status": {"type": "string"},
        },
    }


# ── JSON-RPC method handlers ─────────────────────────────────────────

async def _handle_initialize(space_id: str, token: str, gateway: dict | None):
    """Handle MCP ``initialize``."""
    if gateway:
        title = gateway.get("name", space_id)
        description = gateway.get("description", "")
    else:
        meta = await _fetch_space_metadata(space_id, token)
        title = meta.get("title", space_id)
        description = meta.get("description", "")

    instructions = f"Query the {title} genie space to analyze structured data using natural language."
    if description:
        instructions += f"\nGenie Space description: {description}"

    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "instructions": instructions,
    }


async def _handle_tools_list(space_id: str, token: str, gateway: dict | None):
    """Handle MCP ``tools/list``."""
    if gateway:
        title = gateway.get("name", space_id)
        description = gateway.get("description", "")
    else:
        meta = await _fetch_space_metadata(space_id, token)
        title = meta.get("title", space_id)
        description = meta.get("description", "")

    return {"tools": _build_tools(space_id, title, description)}


async def _handle_query_space(
    url_space_id: str,
    real_space_id: str,
    arguments: dict,
    token: str,
    identity: str,
    gateway: dict | None,
):
    """Handle ``tools/call`` for ``query_space_{space_id}``."""
    query_text = arguments.get("query", "")
    conversation_id = arguments.get("conversation_id")

    if not query_text:
        structured = _build_structured_content(
            "FAILED", "", "",
            text_attachments=["No query provided."],
        )
        return _wrap_tool_result(structured, is_error=True)

    rs = _build_runtime_settings(token, real_space_id, gateway=gateway)

    original_query_text = query_text
    space_context = await get_space_context(real_space_id, rs)
    if rs.question_normalization_enabled:
        query_text = await split_by_intent(query_text, rs, space_context=space_context)
        query_text = await normalize_question(query_text, rs, space_context=space_context)

    # Embedding + cache lookup
    query_embedding = None
    cached = None
    try:
        query_embedding = embedding_service.get_embedding(query_text, rs)
        cache_namespace = gateway.get("id") if gateway else real_space_id
        cached = await _db.db_service.search_similar_query(
            query_embedding, identity, rs.similarity_threshold,
            cache_namespace, rs, shared_cache=rs.shared_cache,
        )
    except Exception as e:
        logger.warning("MCP cache lookup failed: %s", e)

    if cached and rs.cache_validation_enabled:
        cache_id, cached_query, sql_query, similarity, cached_original = cached
        is_valid = await validate_cache_entry(
            original_query_text, cached_original, rs, space_context=space_context,
        )
        if not is_valid:
            logger.info("MCP LLM validation rejected cache hit id=%s", cache_id)
            cached = None

    # ── Cache HIT ─────────────────────────────────────────────────
    if cached:
        cache_id, cached_query, sql_query, similarity, cached_original = cached
        logger.info("MCP CACHE HIT sim=%.3f sql=%s", similarity, sql_query[:80] if sql_query else "")

        conv_id, msg_id, att_id = _make_synthetic_ids()

        statement_response = None
        if sql_query:
            try:
                statement_response = await _execute_sql_raw(sql_query, rs)
            except Exception as e:
                logger.warning("MCP cache hit SQL execution failed: %s", e)

        query_attachments = []
        if sql_query:
            qa = {"query": sql_query, "description": "Cached query — SQL re-executed against warehouse."}
            if statement_response:
                qa["statement_response"] = statement_response
            query_attachments.append(qa)

        text_attachments = ["This result was served from the semantic cache."]

        structured = _build_structured_content(
            "COMPLETED", conv_id, msg_id,
            query_attachments=query_attachments,
            text_attachments=text_attachments,
        )

        # Store for poll_response compatibility and query log
        _synthetic_messages[msg_id] = {
            "conversation_id": conv_id,
            "message_id": msg_id,
            "status": "COMPLETED",
            "attachments": [],
            "_mcp_structured": structured,
            "_proxy": {"stage": "completed", "from_cache": True, "sql_query": sql_query, "result": None},
        }

        try:
            await _db.db_service.save_query_log(
                query_id=msg_id,
                query_text=original_query_text,
                identity=identity,
                stage="completed",
                from_cache=True,
                gateway_id=gateway.get("id") if gateway else None,
                runtime_settings=rs,
            )
        except Exception as e:
            logger.warning("MCP failed to save cache hit query log: %s", e)

        return _wrap_tool_result(structured)

    # ── Cache MISS → background processing ────────────────────────
    conv_id, msg_id, att_id = _make_synthetic_ids()

    pending_text = (
        f"Query is still processing. Use the poll_response_{url_space_id} "
        "tool with conversation_id and message_id to poll until the message "
        "reaches a completed state."
    )
    structured = _build_structured_content(
        "EXECUTING_QUERY", conv_id, msg_id,
        text_attachments=[pending_text],
    )

    _synthetic_messages[msg_id] = {
        "conversation_id": conv_id,
        "message_id": msg_id,
        "status": "EXECUTING_QUERY",
        "attachments": [],
        "_mcp_structured": structured,
        "_proxy": {"stage": "cache_miss", "from_cache": False, "sql_query": None, "result": None},
    }

    task = asyncio.create_task(_process_genie_background(
        space_id=real_space_id,
        query_text=query_text,
        original_query_text=original_query_text,
        query_embedding=query_embedding,
        identity=identity,
        token=token,
        rs=rs,
        msg_id=msg_id,
        att_id=att_id,
        conversation_id=conversation_id,
        gateway_id=gateway.get("id") if gateway else None,
    ))

    def _on_task_done(t):
        exc = t.exception() if not t.cancelled() else None
        if exc:
            logger.error("MCP background task crashed msg_id=%s: %s", msg_id, exc, exc_info=exc)
            fail_structured = _build_structured_content(
                "FAILED", conv_id, msg_id,
                text_attachments=[f"Query processing failed: {exc}"],
            )
            _synthetic_messages[msg_id] = {
                "conversation_id": conv_id,
                "message_id": msg_id,
                "status": "FAILED",
                "attachments": [],
                "_mcp_structured": fail_structured,
                "_proxy": {"stage": "failed", "from_cache": False, "sql_query": None, "result": None},
            }

    task.add_done_callback(_on_task_done)
    logger.info("MCP CACHE MISS: queued background msg_id=%s", msg_id)

    return _wrap_tool_result(structured)


async def _handle_poll_response(
    url_space_id: str,
    real_space_id: str,
    arguments: dict,
    token: str,
    gateway: dict | None,
):
    """Handle ``tools/call`` for ``poll_response_{space_id}``."""
    conversation_id = arguments.get("conversation_id", "")
    message_id = arguments.get("message_id", "")

    stored = _synthetic_messages.get(message_id)
    if not stored:
        structured = _build_structured_content(
            "FAILED", conversation_id, message_id,
            text_attachments=[f"Message {message_id} not found."],
        )
        return _wrap_tool_result(structured, is_error=True)

    status = stored.get("status", "EXECUTING_QUERY")

    # If still processing, return current state
    if status == "EXECUTING_QUERY":
        pending_text = (
            f"Query is still processing. Use the poll_response_{url_space_id} "
            "tool with conversation_id and message_id to poll until the message "
            "reaches a completed state."
        )
        structured = _build_structured_content(
            status, conversation_id, message_id,
            text_attachments=[pending_text],
        )
        return _wrap_tool_result(structured)

    # Completed or failed — build the final response
    if status == "COMPLETED":
        proxy = stored.get("_proxy", {})
        sql_query = proxy.get("sql_query")

        # If we already have MCP structured content cached, return it
        if stored.get("_mcp_structured"):
            return _wrap_tool_result(stored["_mcp_structured"])

        # Lock per message to prevent concurrent polls from double-executing SQL
        lock = _poll_locks.setdefault(message_id, asyncio.Lock())
        async with lock:
            # Re-check after acquiring — another coroutine may have built it
            if stored.get("_mcp_structured"):
                return _wrap_tool_result(stored["_mcp_structured"])

            rs = _build_runtime_settings(token, real_space_id, gateway=gateway)

            query_attachments = []
            text_attachments = []

            if sql_query:
                statement_response = None
                try:
                    statement_response = await _execute_sql_raw(sql_query, rs)
                except Exception as e:
                    logger.warning("MCP poll SQL execution failed: %s", e)

                qa = {"query": sql_query, "description": "Query result from Genie."}
                if statement_response:
                    qa["statement_response"] = statement_response
                query_attachments.append(qa)

            for att in stored.get("attachments", []):
                if isinstance(att, dict) and att.get("text"):
                    text_content = att["text"]
                    if isinstance(text_content, dict):
                        text_attachments.append(text_content.get("content", ""))
                    else:
                        text_attachments.append(str(text_content))

            if not text_attachments:
                if proxy.get("from_cache"):
                    text_attachments.append("This result was served from the semantic cache.")
                else:
                    text_attachments.append("Query completed successfully.")

            structured = _build_structured_content(
                "COMPLETED", conversation_id, message_id,
                query_attachments=query_attachments,
                text_attachments=text_attachments,
            )

            stored["_mcp_structured"] = structured

        return _wrap_tool_result(structured)

    # FAILED or other terminal status
    error_msg = stored.get("error", {})
    if isinstance(error_msg, dict):
        error_msg = error_msg.get("error", "Unknown error")
    structured = _build_structured_content(
        status, conversation_id, message_id,
        text_attachments=[str(error_msg)],
    )
    return _wrap_tool_result(structured, is_error=True)


# ── Diagnostic endpoint (temporary) ──────────────────────────────────

@mcp_router.get("/diag/{space_id}")
async def mcp_diag(space_id: str, request: Request):
    """Diagnose cache flow: embedding → search. Returns step-by-step results."""
    token = extract_bearer_token(request)
    identity = request.headers.get("X-Forwarded-Email", "diag-user")
    real_space_id, gateway = await _resolve_gateway_space_id(space_id)
    rs = _build_runtime_settings(token, real_space_id, gateway=gateway)
    query = request.query_params.get("q", "How many orders?")

    steps = {"query": query, "identity": identity, "space_id": real_space_id,
             "gateway_id": gateway.get("id") if gateway else None,
             "storage_backend": rs.storage_backend,
             "embedding_provider": rs.embedding_provider}

    # Step 1: Embedding
    try:
        emb = embedding_service.get_embedding(query, rs)
        steps["embedding"] = {"status": "ok", "dim": len(emb)}
    except Exception as e:
        steps["embedding"] = {"status": "error", "error": f"{type(e).__name__}: {e}"}
        return steps

    # Step 2: Cache search
    cache_ns = gateway.get("id") if gateway else real_space_id
    try:
        cached = await _db.db_service.search_similar_query(
            emb, identity, rs.similarity_threshold,
            cache_ns, rs, shared_cache=rs.shared_cache,
        )
        if cached:
            steps["search"] = {"status": "hit", "id": cached[0], "query": cached[1][:60],
                               "similarity": cached[3]}
        else:
            steps["search"] = {"status": "miss"}
    except Exception as e:
        steps["search"] = {"status": "error", "error": f"{type(e).__name__}: {e}"}

    return steps


# ── Main endpoint ─────────────────────────────────────────────────────

@mcp_router.post("/genie/{space_id}")
async def mcp_endpoint(space_id: str, request: Request):
    """Streamable HTTP MCP endpoint — handles all JSON-RPC 2.0 messages."""
    try:
        body = await request.json()
    except Exception:
        return _jsonrpc_error(None, -32700, "Parse error")

    method = body.get("method", "")
    req_id = body.get("id")
    params = body.get("params", {})

    # Notifications have no id and expect no response
    if method == "notifications/initialized":
        return JSONResponse(content=None, status_code=204)

    token = extract_bearer_token(request)
    identity = request.headers.get("X-Forwarded-Email", "mcp-user")

    # Resolve gateway
    real_space_id, gateway = await _resolve_gateway_space_id(space_id)

    if method == "initialize":
        result = await _handle_initialize(real_space_id, token, gateway)
        return _jsonrpc_ok(req_id, result)

    if method == "tools/list":
        # Return tools using the URL space_id (gateway_id), not the resolved one
        result = await _handle_tools_list(space_id, token, gateway)
        return _jsonrpc_ok(req_id, result)

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == f"query_space_{space_id}":
            result = await _handle_query_space(
                space_id, real_space_id, arguments, token, identity, gateway,
            )
            return _jsonrpc_ok(req_id, result)

        if tool_name == f"poll_response_{space_id}":
            result = await _handle_poll_response(
                space_id, real_space_id, arguments, token, gateway,
            )
            return _jsonrpc_ok(req_id, result)

        return _jsonrpc_error(req_id, -32601, f"Tool not found: {tool_name}")

    return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")


# ── Router MCP ────────────────────────────────────────────────────────
#
# Parallel surface to the gateway MCP above, but scoped to a router. The
# router runs a selector LLM internally — the agent sees ONE `ask` tool that
# decomposes, picks the right gateway(s), and fans out, plus `list_rooms` for
# catalog inspection. If you want per-gateway tools, point clients at the
# gateway MCP (`/api/2.0/mcp/genie/{space_id}`) instead.

import time as _time


def _build_router_tools(router_id: str, router_cfg: dict) -> list:
    """Tool list for ``tools/list`` on a router MCP.

    Description bakes in the router's name + active member catalog so the
    agent has enough context to phrase good questions without a separate
    discovery call. ``list_rooms`` stays available for richer inspection.
    """
    name = router_cfg.get("name") or router_id
    description = router_cfg.get("description") or ""
    members = router_cfg.get("members") or []
    active = [m for m in members if not m.get("disabled")]

    member_lines = []
    for m in active:
        title = m.get("title") or m.get("gateway_id")
        when = (m.get("when_to_use") or "").strip()
        line = f"- {title}"
        if when:
            line += f": {when}"
        member_lines.append(line)
    catalog_block = "\n".join(member_lines) if member_lines else "(no active members)"

    ask_desc = (
        f"Ask a natural-language data question against the {name} router.\n"
        "The router's selector decides which underlying Genie space(s) handle "
        "the question (decomposing into sub-questions when the question spans "
        "multiple sources) and returns the merged results.\n"
        f"{('Router description: ' + description) if description else ''}\n"
        "Active member spaces and when to use each:\n"
        f"{catalog_block}\n"
        "Returns a structured response with the routing decision (which "
        "spaces were picked and why) plus per-source results (SQL, rows, "
        "errors)."
    )
    list_desc = (
        f"List the active member spaces of the {name} router along with their "
        "catalog metadata (when_to_use, sample questions, tables). Useful for "
        "discovery before phrasing a question. Optional ``filter`` does a "
        "case-insensitive substring match against title and when_to_use."
    )

    return [
        {
            "name": f"ask_{router_id}",
            "description": ask_desc,
            "inputSchema": {
                "type": "object",
                "required": ["question"],
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Natural-language data question.",
                    },
                    "hints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional hints to bias the selector (e.g. preferred member titles).",
                    },
                },
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "router_id": {"type": "string"},
                    "question": {"type": "string"},
                    "routing": {"type": "object"},
                    "diagnostics": {"type": "object"},
                    "sources": {"type": "array", "items": {"type": "object"}},
                    "elapsed_ms": {"type": "integer"},
                    "trace_id": {"type": ["string", "null"]},
                },
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": f"list_rooms_{router_id}",
            "description": list_desc,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "description": "Case-insensitive substring filter applied to title + when_to_use.",
                    },
                },
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "router_id": {"type": "string"},
                    "name": {"type": "string"},
                    "members": {"type": "array", "items": {"type": "object"}},
                },
            },
            "annotations": {"readOnlyHint": True},
        },
    ]


def _wrap_router_result(payload: dict, is_error: bool = False) -> dict:
    """Match the gateway MCP envelope: text content + structuredContent."""
    return {
        "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
        "isError": is_error,
        "structuredContent": payload,
    }


async def _handle_router_initialize(router_cfg: dict):
    name = router_cfg.get("name") or router_cfg.get("id")
    description = router_cfg.get("description") or ""
    instructions = (
        f"Router '{name}' multiplexes several Genie spaces behind a selector "
        "LLM. Use ``ask`` to send a natural-language question (the router "
        "picks the right space(s) and merges results) or ``list_rooms`` to "
        "inspect the catalog before asking."
    )
    if description:
        instructions += f"\nDescription: {description}"

    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "instructions": instructions,
    }


async def _handle_router_ask(router_cfg: dict, arguments: dict, token: str, identity: str) -> dict:
    """Run decompose → select → DAG-execute for one MCP ask call.

    Synchronous: blocks until ``_execute_dag`` finishes (which itself polls
    each gateway dispatch in-process up to ``_DISPATCH_POLL_TIMEOUT_S``).
    Returns the same payload shape as ``POST /api/v1/routers/{id}/query``.
    """
    question = (arguments.get("question") or "").strip()
    if not question:
        return _wrap_router_result(
            {"error": "question is required", "router_id": router_cfg["id"]},
            is_error=True,
        )

    hints = arguments.get("hints") or None
    router_id = router_cfg["id"]
    experiment_id = tracing.resolve_experiment_id(router_cfg.get("mlflow_experiment_path"))

    async with tracing.start_router_root_span(
        "router.query",
        experiment_id=experiment_id,
        router_id=router_id,
        span_type="AGENT",
        inputs={"question": question, "hints": hints},
        attributes={
            "router_id": router_id,
            "user_identity": identity,
            "mode": "mcp_query",
        },
    ) as root:
        t0 = _time.monotonic()
        decision, meta = await _resolve_decision(
            router_cfg, question, hints, token, use_cache=True,
        )

        if not decision.picks:
            elapsed_ms = int((_time.monotonic() - t0) * 1000)
            root.set_outputs({
                "n_picks": 0,
                "decomposed": decision.decomposed,
                "rationale": decision.rationale,
                "elapsed_ms": elapsed_ms,
            })
            trace_id = tracing.current_trace_id()
            payload = {
                "router_id": router_id,
                "question": question,
                "routing": decision.model_dump(),
                "diagnostics": meta,
                "sources": [],
                "elapsed_ms": elapsed_ms,
                "trace_id": trace_id,
            }
            return _wrap_router_result(payload)

        results, dag_stats = await _execute_dag(decision.picks, token, identity)
        elapsed_ms = int((_time.monotonic() - t0) * 1000)
        n_ok = sum(1 for r in results if r.get("status") == "COMPLETED")
        n_skipped = sum(1 for r in results if r.get("status") == "SKIPPED")
        root.set_outputs({
            "n_picks": len(decision.picks),
            "decomposed": decision.decomposed,
            "rationale": decision.rationale,
            "n_ok": n_ok,
            "n_failed": len(results) - n_ok - n_skipped,
            "n_skipped": n_skipped,
            "n_stages": dag_stats["n_stages"],
            "n_skipped_upstream_failed": dag_stats["n_skipped_upstream_failed"],
            "n_skipped_binding_failed": dag_stats["n_skipped_binding_failed"],
            "elapsed_ms": elapsed_ms,
        })
        trace_id = tracing.current_trace_id()

    payload = {
        "router_id": router_id,
        "question": question,
        "routing": decision.model_dump(),
        "diagnostics": {**meta, **dag_stats},
        "sources": results,
        "elapsed_ms": elapsed_ms,
        "trace_id": trace_id,
    }
    is_error = n_ok == 0  # no successful sources ⇒ surface as error to the agent
    return _wrap_router_result(payload, is_error=is_error)


def _handle_router_list_rooms(router_cfg: dict, arguments: dict) -> dict:
    """Catalog inspection — active members with metadata, optional substring filter."""
    flt = (arguments.get("filter") or "").strip().lower()
    members = router_cfg.get("members") or []
    out = []
    for m in members:
        if m.get("disabled"):
            continue
        if flt:
            haystack = " ".join([
                str(m.get("title") or ""),
                str(m.get("when_to_use") or ""),
                str(m.get("gateway_id") or ""),
            ]).lower()
            if flt not in haystack:
                continue
        out.append({
            "gateway_id": m.get("gateway_id"),
            "title": m.get("title"),
            "ordinal": m.get("ordinal"),
            "when_to_use": m.get("when_to_use"),
            "tables": m.get("tables") or [],
            "sample_questions": m.get("sample_questions") or [],
        })
    out.sort(key=lambda x: (x.get("ordinal") or 0, x.get("title") or ""))
    payload = {
        "router_id": router_cfg["id"],
        "name": router_cfg.get("name"),
        "members": out,
    }
    return _wrap_router_result(payload)


@mcp_router.post("/router/{router_id}")
async def mcp_router_endpoint(router_id: str, request: Request):
    """Streamable HTTP MCP endpoint for a router (JSON-RPC 2.0)."""
    try:
        body = await request.json()
    except Exception:
        return _jsonrpc_error(None, -32700, "Parse error")

    method = body.get("method", "")
    req_id = body.get("id")
    params = body.get("params", {})

    if method == "notifications/initialized":
        return JSONResponse(content=None, status_code=204)

    # RBAC: match the REST `/routers/{id}/query` endpoint contract.
    try:
        identity, _role_token, _role = await require_role(request, "use")
    except Exception as e:
        # Bubble HTTPExceptions up as JSON-RPC errors so MCP clients see them.
        from fastapi import HTTPException as _HTTPExc
        if isinstance(e, _HTTPExc):
            return _jsonrpc_error(req_id, -32001, e.detail, {"status": e.status_code})
        raise

    # Token used for downstream Genie/warehouse calls (allows SP fallback so
    # the router endpoint behaves consistently with `POST /routers/{id}/query`).
    token = resolve_user_token_optional(request)
    if not identity:
        identity = "mcp-user"

    router_cfg = await _db.db_service.get_router(router_id, include_members=True)
    if not router_cfg:
        return _jsonrpc_error(req_id, -32602, f"Router not found: {router_id}")

    if method == "initialize":
        return _jsonrpc_ok(req_id, await _handle_router_initialize(router_cfg))

    if method == "tools/list":
        return _jsonrpc_ok(req_id, {"tools": _build_router_tools(router_id, router_cfg)})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}

        if tool_name == f"ask_{router_id}":
            try:
                result = await _handle_router_ask(router_cfg, arguments, token, identity)
            except Exception as e:
                logger.exception("Router MCP ask failed")
                result = _wrap_router_result(
                    {"error": f"{type(e).__name__}: {e}", "router_id": router_id},
                    is_error=True,
                )
            return _jsonrpc_ok(req_id, result)

        if tool_name == f"list_rooms_{router_id}":
            return _jsonrpc_ok(req_id, _handle_router_list_rooms(router_cfg, arguments))

        return _jsonrpc_error(req_id, -32601, f"Tool not found: {tool_name}")

    return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")
