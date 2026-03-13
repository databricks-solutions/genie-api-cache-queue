"""
Drop-in replacement for the Databricks Genie Conversation API.
Mirrors the exact same endpoints and response format so callers only need to change the base URL.
Adds transparent caching, rate-limit management, queueing, and retry.
"""

import logging
import uuid
import asyncio
import httpx
from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.config import get_settings
from app.auth import ensure_https
from app.services.embedding_service import embedding_service
from app.services.genie_service import genie_service, GenieRateLimitError
from app.services.queue_service import queue_service
import app.services.database as _db

logger = logging.getLogger(__name__)
settings = get_settings()

genie_clone_router = APIRouter()

# In-memory store for synthetic (cache/queue) messages
_synthetic_messages: Dict[str, dict] = {}

# Prefix for synthetic IDs to distinguish from real Genie IDs
CONV_PREFIX = "ccache_"
MSG_PREFIX = "mcache_"
ATT_PREFIX = "acache_"


# --- Helpers ---

def _extract_token(request: Request) -> str:
    """Extract auth token from request headers."""
    forwarded = request.headers.get("X-Forwarded-Access-Token", "").strip()
    if forwarded:
        return forwarded

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        if token:
            return token

    if request.headers.get("X-Forwarded-Email"):
        from app.auth import get_service_principal_token
        sp_token = get_service_principal_token()
        if sp_token:
            return sp_token

    raise HTTPException(status_code=401, detail="Missing authentication.")


def _build_runtime_settings(token: str, space_id: str):
    """Build RuntimeSettings for the pipeline."""
    from app.models import RuntimeConfig
    from app.runtime_config import RuntimeSettings

    rc = RuntimeConfig(
        auth_mode="user",
        user_pat=token,
        genie_space_id=space_id,
        sql_warehouse_id=settings.sql_warehouse_id or None,
        similarity_threshold=settings.similarity_threshold,
        max_queries_per_minute=settings.max_queries_per_minute,
        cache_ttl_hours=settings.cache_ttl_hours,
        embedding_provider=settings.embedding_provider,
        databricks_embedding_endpoint=settings.databricks_embedding_endpoint,
        storage_backend="lakebase" if settings.storage_backend == "pgvector" else settings.storage_backend,
        lakebase_instance_name=settings.lakebase_instance or None,
        lakebase_catalog=settings.lakebase_catalog or None,
        lakebase_schema=settings.lakebase_schema or None,
        cache_table_name=settings.pgvector_table_name or None,
    )
    return RuntimeSettings(rc, None, None)


def _make_synthetic_ids():
    """Generate synthetic conversation_id, message_id, attachment_id."""
    uid = uuid.uuid4().hex[:24]
    return f"{CONV_PREFIX}{uid}", f"{MSG_PREFIX}{uid}", f"{ATT_PREFIX}{uid}"


def _format_cache_hit_response(conv_id, msg_id, att_id, sql_query, identity):
    """Format a cache hit as a Genie API response."""
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
        "created_timestamp": None,
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


# --- Endpoints ---

@genie_clone_router.post("/spaces/{space_id}/start-conversation")
async def clone_start_conversation(space_id: str, body: GenieContentBody, request: Request):
    """Clone of POST /api/2.0/genie/spaces/{space_id}/start-conversation.
    Adds cache lookup, rate limiting, and queueing transparently."""
    token = _extract_token(request)
    rs = _build_runtime_settings(token, space_id)
    identity = request.headers.get("X-Forwarded-Email", "api-user")
    query_text = body.content

    # Generate embedding and check cache
    try:
        query_embedding = embedding_service.get_embedding(query_text, rs)
        cached = await _db.db_service.search_similar_query(
            query_embedding, identity, rs.similarity_threshold,
            space_id, rs, shared_cache=rs.shared_cache,
        )
    except Exception as e:
        logger.warning("Cache lookup failed: %s, proceeding without cache", e)
        query_embedding = None
        cached = None

    if cached:
        cache_id, cached_query, sql_query, similarity = cached
        logger.info("Genie clone CACHE HIT: similarity=%.3f sql=%s", similarity, sql_query[:80])

        conv_id, msg_id, att_id = _make_synthetic_ids()
        response = _format_cache_hit_response(conv_id, msg_id, att_id, sql_query, identity)

        _synthetic_messages[msg_id] = response
        _synthetic_messages[att_id] = {"sql_query": sql_query, "from_cache": True}

        return response

    # Cache miss — check rate limit
    if not queue_service.backend.check_rate_limit(identity, rs.max_queries_per_minute):
        logger.info("Genie clone rate limited, queuing query")
        conv_id, msg_id, att_id = _make_synthetic_ids()

        # Queue the work
        queue_item_id = str(uuid.uuid4())
        queue_service.add_to_queue(queue_item_id, {
            "query_text": query_text,
            "identity": identity,
            "query_embedding": query_embedding,
            "runtime_config": rs.runtime.model_dump() if rs.runtime else None,
            "user_token": None,
            "user_email": identity,
            "_synthetic_msg_id": msg_id,
            "_synthetic_att_id": att_id,
        })

        response = {
            "conversation_id": conv_id,
            "message_id": msg_id,
            "status": "EXECUTING_QUERY",
            "attachments": [],
        }
        _synthetic_messages[msg_id] = response
        # Background task will update _synthetic_messages when done
        asyncio.create_task(_process_queued_genie(
            queue_item_id, space_id, query_text, query_embedding, identity, token, rs, msg_id, att_id
        ))

        return response

    # Rate limit OK — call Genie directly
    logger.info("Genie clone calling Genie API for: %s", query_text[:60])
    try:
        result = await genie_service.start_conversation(space_id, query_text, rs)
    except GenieRateLimitError as e:
        logger.warning("Genie 429, queuing: %s", e)
        conv_id, msg_id, att_id = _make_synthetic_ids()
        response = {
            "conversation_id": conv_id,
            "message_id": msg_id,
            "status": "EXECUTING_QUERY",
            "attachments": [],
        }
        _synthetic_messages[msg_id] = response
        asyncio.create_task(_process_queued_genie(
            str(uuid.uuid4()), space_id, query_text, query_embedding, identity, token, rs, msg_id, att_id,
            delay=e.retry_after,
        ))
        return response

    # Save to cache
    if result.get("status") == "COMPLETED" and result.get("sql_query") and query_embedding:
        try:
            await _db.db_service.save_query_cache(
                query_text, query_embedding, result["sql_query"],
                identity, space_id, rs,
            )
        except Exception as e:
            logger.warning("Failed to save cache: %s", e)

    return result


@genie_clone_router.post("/spaces/{space_id}/conversations/{conversation_id}/messages")
async def clone_create_message(space_id: str, conversation_id: str, body: GenieContentBody, request: Request):
    """Clone of POST create-message. Follow-up messages with cache support."""
    token = _extract_token(request)
    rs = _build_runtime_settings(token, space_id)
    identity = request.headers.get("X-Forwarded-Email", "api-user")
    query_text = body.content

    # Check cache for follow-up too
    try:
        query_embedding = embedding_service.get_embedding(query_text, rs)
        cached = await _db.db_service.search_similar_query(
            query_embedding, identity, rs.similarity_threshold,
            space_id, rs, shared_cache=rs.shared_cache,
        )
    except Exception:
        query_embedding = None
        cached = None

    if cached:
        cache_id, cached_query, sql_query, similarity = cached
        conv_id, msg_id, att_id = _make_synthetic_ids()
        response = _format_cache_hit_response(conv_id, msg_id, att_id, sql_query, identity)
        _synthetic_messages[msg_id] = response
        _synthetic_messages[att_id] = {"sql_query": sql_query, "from_cache": True}
        return response

    # Cache miss — call Genie
    if conversation_id.startswith(CONV_PREFIX):
        # Previous conversation was synthetic (cache hit) — start fresh with context
        logger.info("Synthetic conv, starting new real conversation")
        result = await genie_service.start_conversation(space_id, query_text, rs)
    else:
        # Real conversation — send follow-up
        try:
            result = await genie_service.send_message(space_id, conversation_id, query_text, rs)
        except Exception:
            logger.warning("send_message failed, falling back to start_conversation")
            result = await genie_service.start_conversation(space_id, query_text, rs)

    if result.get("status") == "COMPLETED" and result.get("sql_query") and query_embedding:
        try:
            await _db.db_service.save_query_cache(
                query_text, query_embedding, result["sql_query"],
                identity, space_id, rs,
            )
        except Exception as e:
            logger.warning("Failed to save cache: %s", e)

    return result


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
        return stored

    # Real message — proxy to Genie
    path = f"/api/2.0/genie/spaces/{space_id}/conversations/{conversation_id}/messages/{message_id}"
    return await _proxy_passthrough(request, "GET", path, token)


@genie_clone_router.get(
    "/spaces/{space_id}/conversations/{conversation_id}/messages/{message_id}/attachments/{attachment_id}/query-result"
)
async def clone_get_query_result(
    space_id: str, conversation_id: str, message_id: str, attachment_id: str, request: Request
):
    """Clone of GET query-result. Returns cached result or proxies to real Genie."""
    token = _extract_token(request)

    if attachment_id.startswith(ATT_PREFIX):
        stored = _synthetic_messages.get(attachment_id)
        if not stored:
            raise HTTPException(status_code=404, detail="Attachment not found")
        return {
            "statement_id": f"cache_{uuid.uuid4().hex[:16]}",
            "status": "SUCCEEDED",
            "manifest": {},
            "result": {"data_array": [], "row_count": 0},
        }

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
    """Clone of POST execute-query. Always proxies to real Genie (re-execution)."""
    token = _extract_token(request)
    path = (
        f"/api/2.0/genie/spaces/{space_id}/conversations/{conversation_id}"
        f"/messages/{message_id}/attachments/{attachment_id}/execute-query"
    )
    return await _proxy_passthrough(request, "POST", path, token)


# --- Background processing for queued queries ---

async def _process_queued_genie(
    queue_id: str, space_id: str, query_text: str, query_embedding,
    identity: str, token: str, rs, msg_id: str, att_id: str,
    delay: float = 0, max_retries: int = 3,
):
    """Process a queued Genie query in the background, updating synthetic message when done."""
    if delay:
        await asyncio.sleep(delay)

    retry_delays = [5, 15, 30]
    for attempt in range(max_retries + 1):
        try:
            result = await genie_service.start_conversation(space_id, query_text, rs)

            if result.get("status") == "COMPLETED":
                sql_query = result.get("sql_query", "")

                if sql_query and query_embedding:
                    try:
                        await _db.db_service.save_query_cache(
                            query_text, query_embedding, sql_query,
                            identity, space_id, rs,
                        )
                    except Exception as e:
                        logger.warning("Queue cache save failed: %s", e)

                # Update synthetic message to COMPLETED
                conv_id = MSG_PREFIX.replace("mcache_", "ccache_") + msg_id[len(MSG_PREFIX):]
                _synthetic_messages[msg_id] = _format_cache_hit_response(
                    conv_id, msg_id, att_id, sql_query, identity
                )
                _synthetic_messages[msg_id]["status"] = "COMPLETED"
                _synthetic_messages[att_id] = {"sql_query": sql_query}
                return

        except GenieRateLimitError as e:
            await asyncio.sleep(e.retry_after)
            continue
        except Exception as e:
            if attempt < max_retries:
                await asyncio.sleep(retry_delays[min(attempt, len(retry_delays) - 1)])
                continue

            _synthetic_messages[msg_id] = {
                "conversation_id": msg_id.replace(MSG_PREFIX, CONV_PREFIX),
                "message_id": msg_id,
                "status": "FAILED",
                "error": {"error": str(e), "type": "INTERNAL_ERROR"},
                "attachments": [],
            }
            return
