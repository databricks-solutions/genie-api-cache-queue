"""
Drop-in replacement for the Databricks Genie Conversation API.
Mirrors the exact same endpoints and response format so callers only need to change the base URL.
Adds transparent caching, rate-limit management, queueing, and retry.

Endpoints:
  GET  /spaces/{space_id}                          — proxy to real Genie
  POST /spaces/{space_id}/start-conversation       — cache + queue + Genie
  POST /spaces/{sid}/conversations/{cid}/messages   — cache + queue + Genie
  GET  /spaces/{sid}/conversations/{cid}/messages/{mid}                                — poll / proxy
  GET  .../messages/{mid}/attachments/{aid}/query-result                               — exec SQL or proxy
  POST .../messages/{mid}/attachments/{aid}/execute-query                              — exec SQL or proxy
"""

import logging
import uuid
import asyncio
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.auth import ensure_https
from app.config import get_settings
from app.api.config_store import get_effective_setting
from app.api.auth_helpers import resolve_user_token
from app.services.embedding_service import embedding_service
from app.services.genie_service import genie_service, GenieRateLimitError, GenieConfigError
from app.utils import exponential_backoff
from app.services.intent_splitter import split_by_intent
from app.services.question_normalizer import normalize_question
from app.services.cache_validator import validate_cache_entry
from app.services.prompt_enricher import get_space_context
from app.services.storage_local import get_local_queue as _get_local_queue
import app.services.database as _db

_rate_limiter = _get_local_queue()

logger = logging.getLogger(__name__)
settings = get_settings()

genie_clone_router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory store for synthetic (cache / queued) messages & attachments
# ---------------------------------------------------------------------------
_synthetic_messages: dict[str, dict] = {}
_message_locks: dict[str, asyncio.Lock] = {}
_SYNTHETIC_MAX = 2000

CONV_PREFIX = "ccache_"
MSG_PREFIX = "mcache_"
ATT_PREFIX = "acache_"


def _sweep_synthetic_messages():
    """Evict oldest completed entries when the store exceeds _SYNTHETIC_MAX.
    Prefers unlocked entries; falls back to oldest locked entries if all are locked.
    """
    overflow = len(_synthetic_messages) - _SYNTHETIC_MAX
    if overflow <= 0:
        return
    evicted = 0
    skipped_locked = []
    for k in list(_synthetic_messages.keys()):
        if evicted >= overflow:
            break
        lock = _message_locks.get(k)
        if lock is not None and lock.locked():
            skipped_locked.append(k)
            continue
        _synthetic_messages.pop(k, None)
        _message_locks.pop(k, None)
        evicted += 1
    remaining = overflow - evicted
    if remaining > 0:
        for k in skipped_locked[:remaining]:
            _synthetic_messages.pop(k, None)
            _message_locks.pop(k, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_message_lock(msg_id: str) -> asyncio.Lock:
    if msg_id not in _message_locks:
        _message_locks[msg_id] = asyncio.Lock()
    return _message_locks[msg_id]


def _release_message_lock(msg_id: str) -> None:
    _message_locks.pop(msg_id, None)


def _extract_token(request: Request) -> str:
    """Extract auth token: passthrough → Bearer → SP fallback."""
    return resolve_user_token(request)


async def _resolve_gateway_space_id(space_id: str) -> tuple[str, dict | None]:
    """Resolve space_id: if it matches a gateway UUID, return (real_genie_space_id, gateway_config).
    Otherwise return (space_id, None) for backward compatibility."""
    try:
        gateway = await _db.db_service.get_gateway(space_id)
        if gateway:
            logger.info("Resolved gateway_id=%s -> genie_space_id=%s", space_id, gateway["genie_space_id"])
            return gateway["genie_space_id"], gateway
    except Exception:
        pass
    return space_id, None


def _build_runtime_settings(token: str, space_id: str, gateway: dict = None):
    """Build RuntimeSettings using server config overrides (PUT /config) + env defaults.
    If a gateway config is provided, its per-gateway settings override globals.
    Uses app SP OAuth for Lakebase cache, caller OAuth for Genie/SQL."""
    from app.models import RuntimeConfig
    from app.runtime_config import RuntimeSettings

    # Per-gateway overrides take priority over global settings
    gw = gateway or {}

    rc = RuntimeConfig(
        genie_space_id=space_id,
        sql_warehouse_id=gw.get("sql_warehouse_id") or get_effective_setting("sql_warehouse_id") or None,
        similarity_threshold=gw.get("similarity_threshold") or get_effective_setting("similarity_threshold"),
        max_queries_per_minute=gw.get("max_queries_per_minute") or get_effective_setting("max_queries_per_minute"),
        cache_ttl_hours=gw.get("cache_ttl_hours") or get_effective_setting("cache_ttl_hours"),
        embedding_provider=gw.get("embedding_provider") or get_effective_setting("embedding_provider"),
        databricks_embedding_endpoint=gw.get("databricks_embedding_endpoint") or get_effective_setting("databricks_embedding_endpoint"),
        storage_backend="lakebase",
        lakebase_instance_name=get_effective_setting("lakebase_instance_name") or get_effective_setting("lakebase_instance") or None,
        lakebase_catalog=get_effective_setting("lakebase_catalog") or None,
        lakebase_schema=get_effective_setting("lakebase_schema") or None,
        cache_table_name=get_effective_setting("cache_table_name") or get_effective_setting("pgvector_table_name") or None,
        shared_cache=gw.get("shared_cache") if gw.get("shared_cache") is not None else get_effective_setting("shared_cache"),
        question_normalization_enabled=gw.get("question_normalization_enabled") if gw.get("question_normalization_enabled") is not None else get_effective_setting("question_normalization_enabled"),
        cache_validation_enabled=gw.get("cache_validation_enabled") if gw.get("cache_validation_enabled") is not None else get_effective_setting("cache_validation_enabled"),
    )
    return RuntimeSettings(rc, user_token=token, user_email=None)


def _make_synthetic_ids():
    uid = uuid.uuid4().hex[:24]
    return f"{CONV_PREFIX}{uid}", f"{MSG_PREFIX}{uid}", f"{ATT_PREFIX}{uid}"


def _format_completed_response(conv_id, msg_id, att_id, sql_query):
    """Format a COMPLETED Genie-compatible response (cache hit or finished background)."""
    attachments = []
    if sql_query:
        attachments.append({
            "attachment_id": att_id,
            "query": {
                "query": sql_query,
                "description": "Result from semantic cache.",
            },
        })
    attachments.append({
        "attachment_id": f"{ATT_PREFIX}txt_{uuid.uuid4().hex[:16]}",
        "text": {"content": "This result was served from the semantic cache."},
    })
    return {
        "conversation_id": conv_id,
        "message_id": msg_id,
        "status": "COMPLETED",
        "attachments": attachments,
    }


def _format_executing_response(conv_id, msg_id):
    """Format an EXECUTING_QUERY response (work in progress)."""
    return {
        "conversation_id": conv_id,
        "message_id": msg_id,
        "status": "EXECUTING_QUERY",
        "attachments": [],
    }


async def _proxy_passthrough(request: Request, method: str, path: str, token: str, body: dict = None):
    """Forward request to the real Genie API."""
    host = ensure_https(settings.databricks_host)
    url = f"{host}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        if method == "GET":
            resp = await client.get(url, headers=headers, timeout=30.0)
        else:
            resp = await client.post(url, headers=headers, json=body, timeout=30.0)

    return JSONResponse(status_code=resp.status_code, content=resp.json())


class GenieContentBody(BaseModel):
    content: str


# ---------------------------------------------------------------------------
# Background processing for queued Genie queries
# ---------------------------------------------------------------------------

async def _process_genie_background(
    space_id: str,
    query_text: str,
    query_embedding,
    identity: str,
    token: str,
    rs,
    msg_id: str,
    att_id: str,
    original_query_text: str = None,
    conversation_id: str = None,
    delay: float = 0,
    max_retries: int = 3,
    gateway_id: str = None,
):
    """Call Genie in the background. Updates _synthetic_messages when done."""
    logger.info(
        "Background task STARTED msg_id=%s space=%s token_len=%d host=%s",
        msg_id, space_id, len(token) if token else 0, rs.databricks_host,
    )
    if delay:
        await asyncio.sleep(delay)

    last_error = None
    attempt = 0
    max_rate_limit_waits = 12  # worst case 12 × 10s = 120s

    while attempt <= max_retries:
        # Wait for rate limit slot (does NOT consume an attempt)
        rate_limit_waits = 0
        while not _rate_limiter.check_rate_limit(identity, rs.max_queries_per_minute):
            rate_limit_waits += 1
            if rate_limit_waits > max_rate_limit_waits:
                logger.warning("Background rate limit wait exhausted for msg_id=%s", msg_id)
                break
            wait = exponential_backoff(rate_limit_waits - 1, base=5.0, cap=10.0)
            logger.info("Background rate limited, waiting %.1fs (wait %d/%d)", wait, rate_limit_waits, max_rate_limit_waits)
            await asyncio.sleep(wait)

        async with _get_message_lock(msg_id):
            if msg_id in _synthetic_messages:
                _synthetic_messages[msg_id].setdefault("_proxy", {})["stage"] = "processing_genie"

        # Genie API always receives the original user question;
        # normalized form is only used for cache key / embedding.
        genie_query = original_query_text or query_text
        try:
            if conversation_id and not conversation_id.startswith(CONV_PREFIX):
                try:
                    result = await genie_service.send_message(space_id, conversation_id, genie_query, rs)
                except GenieConfigError:
                    raise
                except Exception:
                    logger.warning("send_message failed, falling back to start_conversation")
                    result = await genie_service.start_conversation(space_id, genie_query, rs)
            else:
                result = await genie_service.start_conversation(space_id, genie_query, rs)


            if result.get("status") == "COMPLETED":
                sql_query = result.get("sql_query", "")

                if sql_query and query_embedding is not None:
                    try:
                        cache_id = await _db.db_service.save_query_cache(
                            query_text, query_embedding, sql_query,
                            identity, gateway_id or space_id, rs,
                            original_query_text=original_query_text,
                            genie_space_id=space_id,
                        )
                        logger.info("Background cache SAVED id=%s query=%s", cache_id, query_text[:50])
                    except Exception as e:
                        logger.error("Background cache save FAILED: %s", e, exc_info=True)
                else:
                    logger.warning("Background cache SKIPPED: sql=%s embedding=%s",
                                   bool(sql_query), query_embedding is not None)

                conv_id = CONV_PREFIX + msg_id[len(MSG_PREFIX):]
                completed = _format_completed_response(conv_id, msg_id, att_id, sql_query)

                real_attachments = result.get("attachments", [])
                if real_attachments:
                    completed["attachments"] = real_attachments

                # Set preliminary _proxy BEFORE the await so status polls see valid state
                completed["_proxy"] = {
                    "stage": "processing_genie",
                    "from_cache": False,
                    "sql_query": sql_query,
                    "result": None,
                }
                async with _get_message_lock(msg_id):
                    _synthetic_messages[msg_id] = completed
                    _synthetic_messages[att_id] = {"sql_query": sql_query, "token": token, "space_id": space_id}
                    for _att in completed.get("attachments", []):
                        if isinstance(_att, dict) and _att.get("query") and _att.get("attachment_id"):
                            _synthetic_messages[_att["attachment_id"]] = {"sql_query": sql_query, "token": token, "space_id": space_id}

                # Now execute SQL (poll arriving here sees stage=processing_genie, not received)
                actual_result = None
                if sql_query:
                    try:
                        sql_exec = await genie_service.execute_sql(sql_query, rs)
                        if sql_exec.get("status") == "SUCCEEDED":
                            actual_result = sql_exec.get("result")
                    except Exception as e:
                        logger.warning("execute_sql after cache miss failed: %s", e)

                # Update _proxy to final state
                async with _get_message_lock(msg_id):
                    _synthetic_messages[msg_id]["_proxy"] = {
                        "stage": "completed",
                        "from_cache": False,
                        "sql_query": sql_query,
                        "result": actual_result,
                    }
                _release_message_lock(msg_id)

                # Save query log
                try:
                    await _db.db_service.save_query_log(
                        query_id=msg_id,
                        query_text=original_query_text or query_text,
                        identity=identity,
                        stage="completed",
                        from_cache=False,
                        gateway_id=gateway_id,
                        runtime_settings=rs,
                    )
                except Exception as e:
                    logger.warning("Failed to save cache miss query log: %s", e)
                return

            # Non-COMPLETED terminal status
            async with _get_message_lock(msg_id):
                _synthetic_messages[msg_id] = {
                    "conversation_id": CONV_PREFIX + msg_id[len(MSG_PREFIX):],
                    "message_id": msg_id,
                    "status": result.get("status", "FAILED"),
                    "attachments": [],
                    "error": result.get("error"),
                    "_proxy": {"stage": "failed", "from_cache": False, "sql_query": None, "result": None},
                }
            _release_message_lock(msg_id)
            return

        except GenieRateLimitError as e:
            attempt += 1
            logger.info("Genie 429 in background, waiting %ss (attempt %d/%d)", e.retry_after, attempt, max_retries + 1)
            await asyncio.sleep(e.retry_after)
            last_error = str(e)
            continue
        except GenieConfigError as e:
            logger.error("Non-retryable Genie error %d for msg_id=%s: %s", e.status_code, msg_id, e.detail)
            async with _get_message_lock(msg_id):
                _synthetic_messages[msg_id] = {
                    "conversation_id": CONV_PREFIX + msg_id[len(MSG_PREFIX):],
                    "message_id": msg_id,
                    "status": "FAILED",
                    "attachments": [],
                    "error": {"error": e.detail, "type": "CONFIG_ERROR"},
                    "_proxy": {"stage": "failed", "from_cache": False, "sql_query": None, "result": None},
                }
            _release_message_lock(msg_id)
            return
        except Exception as e:
            last_error = str(e)
            attempt += 1
            if attempt <= max_retries:
                wait = exponential_backoff(attempt - 1, base=2.0, cap=30.0)
                logger.warning("Background Genie attempt %d failed: %s, retrying in %.1fs", attempt, e, wait)
                await asyncio.sleep(wait)
                continue
            break

    # Fallback: all retries exhausted — ALWAYS set FAILED so client stops polling
    logger.error("Background processing failed for msg_id=%s: %s", msg_id, last_error)
    async with _get_message_lock(msg_id):
        _synthetic_messages[msg_id] = {
            "conversation_id": CONV_PREFIX + msg_id[len(MSG_PREFIX):],
            "message_id": msg_id,
            "status": "FAILED",
            "attachments": [],
            "error": {"error": last_error or "All retries exhausted", "type": "INTERNAL_ERROR"},
            "_proxy": {"stage": "failed", "from_cache": False, "sql_query": None, "result": None},
        }
    _release_message_lock(msg_id)


# ---------------------------------------------------------------------------
# Core logic shared by start-conversation and create-message
# ---------------------------------------------------------------------------

async def _handle_query(
    space_id: str,
    query_text: str,
    token: str,
    identity: str,
    conversation_id: str = None,
    gateway: dict = None,
):
    """
    Shared handler for start-conversation and create-message.
    1. Check cache → if hit, return COMPLETED immediately.
    2. If miss → return EXECUTING_QUERY and process in background.
    space_id must already be the real Genie space_id (resolved by caller).
    """
    rs = _build_runtime_settings(token, space_id, gateway=gateway)

    original_query_text = query_text
    space_context = await get_space_context(space_id, rs)
    if rs.question_normalization_enabled:
        query_text = await split_by_intent(query_text, rs, space_context=space_context)
        query_text = await normalize_question(query_text, rs, space_context=space_context)

    # Generate embedding and check cache
    query_embedding = None
    cached = None
    try:
        query_embedding = embedding_service.get_embedding(query_text, rs)
        logger.info("Embedding generated: len=%s for query=%s", len(query_embedding) if query_embedding else None, query_text[:40])
        cache_namespace = gateway.get("id") if gateway else space_id
        cached = await _db.db_service.search_similar_query(
            query_embedding, identity, rs.similarity_threshold,
            cache_namespace, rs, shared_cache=rs.shared_cache,
        )
    except Exception as e:
        logger.warning("Cache lookup failed: %s — proceeding without cache", e)

    if cached and rs.cache_validation_enabled:
        cache_id, cached_query, sql_query, similarity, cached_original = cached
        is_valid = await validate_cache_entry(original_query_text, cached_original, rs, space_context=space_context)
        if not is_valid:
            logger.info("LLM validation rejected cache hit id=%s — treating as MISS", cache_id)
            cached = None

    # --- Cache HIT: execute cached SQL against warehouse ---
    if cached:
        cache_id, cached_query, sql_query, similarity, cached_original = cached
        logger.info("Clone CACHE HIT: sim=%.3f sql=%s", similarity, sql_query[:80] if sql_query else "")

        conv_id, msg_id, att_id = _make_synthetic_ids()

        # Execute the cached SQL to get fresh data
        sql_result = None
        try:
            sql_result = await genie_service.execute_sql(sql_query, rs)
        except Exception as e:
            logger.warning("Cache hit SQL execution failed: %s", e)

        statement_id = sql_result.get("statement_id") if sql_result else None
        row_count = 0
        if sql_result and sql_result.get("result"):
            row_count = sql_result["result"].get("row_count", 0)

        response = {
            "conversation_id": conv_id,
            "message_id": msg_id,
            "status": "COMPLETED",
            "attachments": [
                {
                    "attachment_id": att_id,
                    "query": {
                        "query": sql_query,
                        "description": "Cached query — SQL re-executed against warehouse.",
                        **({"statement_id": statement_id} if statement_id else {}),
                        "query_result_metadata": {"row_count": row_count},
                    },
                },
                {
                    "attachment_id": f"{ATT_PREFIX}txt_{uuid.uuid4().hex[:16]}",
                    "text": {"content": "This result was served from the semantic cache."},
                },
            ],
        }
        # Extract inner result (same format as cache miss)
        actual_result = None
        if sql_result and sql_result.get("status") == "SUCCEEDED":
            actual_result = sql_result.get("result")

        response["_proxy"] = {
            "stage": "completed",
            "from_cache": True,
            "sql_query": sql_query,
            "result": actual_result,
        }
        _sweep_synthetic_messages()
        async with _get_message_lock(msg_id):
            _synthetic_messages[msg_id] = response
            _synthetic_messages[att_id] = {"sql_query": sql_query, "token": token, "space_id": space_id}
        _release_message_lock(msg_id)

        # Save query log
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
            logger.warning("Failed to save cache hit query log: %s", e)

        return {k: v for k, v in response.items() if not k.startswith("_")}

    # --- Cache MISS → non-blocking background processing ---
    conv_id, msg_id, att_id = _make_synthetic_ids()
    response = _format_executing_response(conv_id, msg_id)
    response["_proxy"] = {"stage": "cache_miss", "from_cache": False, "sql_query": None, "result": None}
    _sweep_synthetic_messages()
    async with _get_message_lock(msg_id):
        _synthetic_messages[msg_id] = response

    task = asyncio.create_task(_process_genie_background(
        space_id=space_id,
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
            logger.error("Background task CRASHED for msg_id=%s: %s", msg_id, exc, exc_info=exc)
            _synthetic_messages[msg_id] = {
                "conversation_id": CONV_PREFIX + msg_id[len(MSG_PREFIX):],
                "message_id": msg_id,
                "status": "FAILED",
                "attachments": [],
                "error": {"error": f"Background task crashed: {exc}", "type": "INTERNAL_ERROR"},
                "_proxy": {"stage": "failed", "from_cache": False, "sql_query": None, "result": None},
            }
            _release_message_lock(msg_id)
        elif t.cancelled():
            _release_message_lock(msg_id)

    task.add_done_callback(_on_task_done)

    logger.info("Clone CACHE MISS: queued background task msg_id=%s token_len=%d host=%s", msg_id, len(token) if token else 0, rs.databricks_host)
    return {k: v for k, v in response.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@genie_clone_router.get("/spaces/{space_id}")
async def clone_get_space(space_id: str, request: Request):
    """Proxy GET space metadata to real Genie API. Resolves gateway_id if needed."""
    token = _extract_token(request)
    real_space_id, _ = await _resolve_gateway_space_id(space_id)
    return await _proxy_passthrough(request, "GET", f"/api/2.0/genie/spaces/{real_space_id}", token)


@genie_clone_router.post("/spaces/{space_id}/start-conversation")
async def clone_start_conversation(space_id: str, body: GenieContentBody, request: Request):
    """Clone of POST /api/2.0/genie/spaces/{space_id}/start-conversation.
    Accepts gateway_id (our UUID) or real Genie space_id. Returns immediately."""
    token = _extract_token(request)
    identity = request.headers.get("X-Forwarded-Email", "api-user")
    real_space_id, gateway = await _resolve_gateway_space_id(space_id)
    return await _handle_query(real_space_id, body.content, token, identity, gateway=gateway)


@genie_clone_router.post("/spaces/{space_id}/conversations/{conversation_id}/messages")
async def clone_create_message(space_id: str, conversation_id: str, body: GenieContentBody, request: Request):
    """Clone of POST create-message. Resolves gateway_id if needed."""
    token = _extract_token(request)
    identity = request.headers.get("X-Forwarded-Email", "api-user")
    real_space_id, gateway = await _resolve_gateway_space_id(space_id)
    return await _handle_query(real_space_id, body.content, token, identity, conversation_id=conversation_id, gateway=gateway)


@genie_clone_router.get(
    "/spaces/{space_id}/conversations/{conversation_id}/messages/{message_id}"
)
async def clone_get_message(space_id: str, conversation_id: str, message_id: str, request: Request):
    """Clone of GET get-message. Returns synthetic result or proxies to real Genie."""
    token = _extract_token(request)

    if message_id.startswith(MSG_PREFIX):
        stored = _synthetic_messages.get(message_id)
        if not stored:
            raise HTTPException(status_code=404, detail="Message not found")
        return {k: v for k, v in stored.items() if not k.startswith("_")}

    # Real message — proxy to Genie
    path = f"/api/2.0/genie/spaces/{space_id}/conversations/{conversation_id}/messages/{message_id}"
    return await _proxy_passthrough(request, "GET", path, token)


@genie_clone_router.get(
    "/spaces/{space_id}/conversations/{conversation_id}/messages/{message_id}/attachments/{attachment_id}/query-result"
)
async def clone_get_query_result(
    space_id: str, conversation_id: str, message_id: str, attachment_id: str, request: Request
):
    """Clone of GET query-result. Executes cached SQL or proxies to real Genie."""
    token = _extract_token(request)

    # Check if we have cached SQL for this attachment (synthetic or registered real Genie ID)
    stored = _synthetic_messages.get(attachment_id)
    if stored and stored.get("sql_query"):
        rs = _build_runtime_settings(token, space_id)
        try:
            result = await genie_service.execute_sql(stored["sql_query"], rs)
            return {"statement_response": result}
        except Exception as e:
            logger.error("Failed to execute cached SQL: %s", e)
            raise HTTPException(status_code=500, detail=f"SQL execution failed: {e}")

    # Unknown attachment — proxy to real Genie (already returns statement_response)
    path = (
        f"/api/2.0/genie/spaces/{space_id}/conversations/{conversation_id}"
        f"/messages/{message_id}/attachments/{attachment_id}/query-result"
    )
    return await _proxy_passthrough(request, "GET", path, token)


@genie_clone_router.post(
    "/spaces/{space_id}/conversations/{conversation_id}/messages/{message_id}/attachments/{attachment_id}/execute-query"
)
async def clone_execute_query(
    space_id: str, conversation_id: str, message_id: str, attachment_id: str, request: Request
):
    """Clone of POST execute-query. Re-executes cached SQL or proxies to real Genie."""
    token = _extract_token(request)

    stored = _synthetic_messages.get(attachment_id)
    if stored and stored.get("sql_query"):
        rs = _build_runtime_settings(token, space_id)
        try:
            result = await genie_service.execute_sql(stored["sql_query"], rs)
            return {"statement_response": result}
        except Exception as e:
            logger.error("Failed to execute cached SQL: %s", e)
            raise HTTPException(status_code=500, detail=f"SQL execution failed: {e}")

    path = (
        f"/api/2.0/genie/spaces/{space_id}/conversations/{conversation_id}"
        f"/messages/{message_id}/attachments/{attachment_id}/execute-query"
    )
    return await _proxy_passthrough(request, "POST", path, token)
