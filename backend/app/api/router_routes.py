"""
Router CRUD + query API routes.

A "router" is a peer to the gateway: it groups several gateway members under a
curated catalog (per-member `when_to_use` + sample questions) so a selector
LLM can decide which gateway handles a given question.

Covers Phase 1 (CRUD for routers and router_members, routing-cache flush) and
Phase 2 (/query and /preview endpoints that actually run the selector and fan
sub-queries out to gateways).
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.api.auth_helpers import require_role, resolve_user_token_optional
from app.api.genie_clone_routes import (
    _handle_query as _gateway_handle_query,
    _synthetic_messages as _gateway_synthetic_messages,
    MSG_PREFIX as _GATEWAY_MSG_PREFIX,
)
from app.config import get_settings
from app.models import (
    RouterCreateRequest,
    RouterMemberCreateRequest,
    RouterMemberUpdateRequest,
    RouterQueryRequest,
    RouterUpdateRequest,
)
from app.services.embedding_service import embedding_service
from app.services.selector import RoomPick, RoutingDecision, select_rooms
from app.services import tracing
import app.services.database as _db

logger = logging.getLogger(__name__)
router_router = APIRouter()
_settings = get_settings()


# --- Router CRUD ---

@router_router.get("/routers")
async def list_routers(req: Request):
    """List all routers (members not hydrated, for efficiency)."""
    await require_role(req, "use")
    try:
        return await _db.db_service.list_routers()
    except Exception as e:
        logger.exception("Error listing routers")
        raise HTTPException(status_code=500, detail=str(e))


@router_router.post("/routers", status_code=201)
async def create_router(body: RouterCreateRequest, req: Request):
    """Create a new router. Owner only."""
    await require_role(req, "owner")
    try:
        now = datetime.now(timezone.utc)
        user_email = req.headers.get("X-Forwarded-Email")

        existing = await _db.db_service.list_routers()
        if any(r["name"].lower() == body.name.lower() for r in existing):
            raise HTTPException(status_code=409, detail=f"A router named '{body.name}' already exists.")

        config = {
            "id": str(uuid.uuid4()),
            "name": body.name,
            "description": body.description or "",
            "status": "active",
            "selector_model": body.selector_model or None,
            "selector_system_prompt": body.selector_system_prompt or None,
            "decompose_enabled": body.decompose_enabled if body.decompose_enabled is not None else True,
            "routing_cache_enabled": body.routing_cache_enabled if body.routing_cache_enabled is not None else True,
            "similarity_threshold": body.similarity_threshold if body.similarity_threshold is not None else 0.92,
            "cache_ttl_hours": body.cache_ttl_hours if body.cache_ttl_hours is not None else 24,
            "created_by": user_email,
            "created_at": now,
            "updated_at": now,
        }

        result = await _db.db_service.create_router(config)

        # Optionally seed initial members from the request body
        if body.members:
            for m in body.members:
                await _add_member(config["id"], m)
            result = await _db.db_service.get_router(config["id"])

        logger.info("Router created: id=%s name=%s by=%s", config["id"], config["name"], user_email)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating router")
        raise HTTPException(status_code=500, detail=str(e))


@router_router.get("/routers/{router_id}")
async def get_router(router_id: str, req: Request):
    """Get a router with hydrated members."""
    await require_role(req, "use")
    try:
        r = await _db.db_service.get_router(router_id, include_members=True)
        if not r:
            raise HTTPException(status_code=404, detail="Router not found")
        return r
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting router")
        raise HTTPException(status_code=500, detail=str(e))


@router_router.put("/routers/{router_id}")
async def update_router(router_id: str, body: RouterUpdateRequest, req: Request):
    """Update router fields. Manage or above."""
    await require_role(req, "manage")
    try:
        updates = body.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        result = await _db.db_service.update_router(router_id, updates)
        if not result:
            raise HTTPException(status_code=404, detail="Router not found")
        logger.info("Router updated: id=%s fields=%s", router_id, list(updates.keys()))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating router")
        raise HTTPException(status_code=500, detail=str(e))


@router_router.delete("/routers/{router_id}")
async def delete_router(router_id: str, req: Request):
    """Hard-delete a router (cascades to members + routing_cache). Owner only."""
    await require_role(req, "owner")
    try:
        deleted = await _db.db_service.delete_router(router_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Router not found")
        logger.info("Router deleted: id=%s", router_id)
        return {"success": True, "message": f"Router {router_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting router")
        raise HTTPException(status_code=500, detail=str(e))


# --- Router members CRUD ---

async def _add_member(router_id: str, body: RouterMemberCreateRequest):
    """Shared helper used by POST /members and the initial-seed path in create_router."""
    gw = await _db.db_service.get_gateway(body.gateway_id)
    if not gw:
        raise HTTPException(status_code=400, detail=f"Gateway {body.gateway_id} not found")

    existing = await _db.db_service.get_router_member(router_id, body.gateway_id)
    if existing:
        raise HTTPException(status_code=409, detail="Gateway is already a member of this router")

    title = body.title or gw.get("name") or body.gateway_id
    member = {
        "router_id": router_id,
        "gateway_id": body.gateway_id,
        "ordinal": body.ordinal if body.ordinal is not None else 0,
        "title": title,
        "when_to_use": body.when_to_use,
        "tables": body.tables or [],
        "sample_questions": body.sample_questions or [],
        "disabled": bool(body.disabled) if body.disabled is not None else False,
    }
    return await _db.db_service.add_router_member(member)


@router_router.post("/routers/{router_id}/members", status_code=201)
async def add_router_member(router_id: str, body: RouterMemberCreateRequest, req: Request):
    """Add a gateway to a router with its catalog metadata. Manage or above."""
    await require_role(req, "manage")
    try:
        r = await _db.db_service.get_router(router_id, include_members=False)
        if not r:
            raise HTTPException(status_code=404, detail="Router not found")
        result = await _add_member(router_id, body)
        logger.info("Router member added: router=%s gateway=%s", router_id, body.gateway_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error adding router member")
        raise HTTPException(status_code=500, detail=str(e))


@router_router.put("/routers/{router_id}/members/{gateway_id}")
async def update_router_member(
    router_id: str, gateway_id: str, body: RouterMemberUpdateRequest, req: Request
):
    """Update per-member catalog metadata (when_to_use, tables, etc.). Manage or above."""
    await require_role(req, "manage")
    try:
        updates = body.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        result = await _db.db_service.update_router_member(router_id, gateway_id, updates)
        if not result:
            raise HTTPException(status_code=404, detail="Router member not found")
        logger.info("Router member updated: router=%s gateway=%s fields=%s",
                    router_id, gateway_id, list(updates.keys()))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating router member")
        raise HTTPException(status_code=500, detail=str(e))


@router_router.delete("/routers/{router_id}/members/{gateway_id}")
async def delete_router_member(router_id: str, gateway_id: str, req: Request):
    """Remove a gateway from a router. Manage or above."""
    await require_role(req, "manage")
    try:
        deleted = await _db.db_service.delete_router_member(router_id, gateway_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Router member not found")
        logger.info("Router member deleted: router=%s gateway=%s", router_id, gateway_id)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting router member")
        raise HTTPException(status_code=500, detail=str(e))


# --- Routing cache flush ---

@router_router.delete("/routers/{router_id}/cache")
async def flush_routing_cache(router_id: str, req: Request):
    """Delete all routing cache rows for a router. Manage or above."""
    await require_role(req, "manage")
    try:
        r = await _db.db_service.get_router(router_id, include_members=False)
        if not r:
            raise HTTPException(status_code=404, detail="Router not found")
        count = await _db.db_service.clear_routing_cache(router_id)
        logger.info("Routing cache flushed: router=%s count=%d", router_id, count)
        return {"deleted": count, "router_id": router_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error flushing routing cache")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Query + preview (Phase 2)
# ---------------------------------------------------------------------------

def _build_runtime_settings_for_embedding(token: str):
    """Build a minimal RuntimeSettings so embedding_service picks the right endpoint.

    The router-selector path doesn't need gateway-scoped caching/validation
    toggles; we only need databricks_host + databricks_token + embedding
    endpoint. Mirrors the shape of build_simple_runtime_settings but we build
    it inline to keep the embedding provider setting configurable globally.
    """
    from app.models import RuntimeConfig
    from app.runtime_config import RuntimeSettings
    return RuntimeSettings(RuntimeConfig(), token, None)


async def _resolve_decision(
    router_cfg: dict,
    question: str,
    hints: list[str] | None,
    token: str,
    use_cache: bool,
) -> tuple[RoutingDecision, dict]:
    """Return (decision, meta).

    meta is a dict with diagnostic fields — cache_hit, selector_ms, embedding_ms,
    cached_question, cached_similarity — suitable for inclusion in the response.
    """
    members = router_cfg.get("members") or []
    active = [m for m in members if not m.get("disabled")]
    meta: dict = {"cache_hit": False, "selector_ms": 0, "embedding_ms": 0}

    if not active:
        return RoutingDecision(picks=[], decomposed=False, rationale="no active members"), meta

    # Single-member shortcut — no LLM call, no cache lookup.
    if len(active) == 1:
        only = active[0]
        return (
            RoutingDecision(
                picks=[RoomPick(gateway_id=only["gateway_id"], sub_question=question)],
                decomposed=False,
                rationale=f"only one active member ({only['gateway_id']})",
            ),
            meta,
        )

    # Routing cache lookup (only when enabled).
    embedding = None
    if use_cache and router_cfg.get("routing_cache_enabled"):
        t0 = time.monotonic()
        try:
            rs = _build_runtime_settings_for_embedding(token)
            embedding = embedding_service.get_embedding(question, rs)
        except Exception as e:
            logger.warning("Router embedding failed: %s — skipping routing cache", e)
        meta["embedding_ms"] = int((time.monotonic() - t0) * 1000)
        if embedding is not None:
            with tracing.span(
                "router.cache.lookup",
                span_type="RETRIEVER",
                inputs={"question": question},
                attributes={
                    "router_id": router_cfg["id"],
                    "similarity_threshold": router_cfg.get("similarity_threshold", 0.92),
                },
            ) as cache_span:
                try:
                    hit = await _db.db_service.lookup_routing_cache(
                        router_cfg["id"], embedding, router_cfg.get("similarity_threshold", 0.92),
                    )
                except Exception as e:
                    logger.warning("Routing cache lookup failed: %s", e)
                    hit = None
                if hit:
                    cache_span.set_outputs({
                        "hit": True,
                        "cached_question": hit["question"],
                        "similarity": hit["similarity"],
                    })
                else:
                    cache_span.set_outputs({"hit": False})
            if hit:
                meta["cache_hit"] = True
                meta["cached_question"] = hit["question"]
                meta["cached_similarity"] = hit["similarity"]
                decision_dict = hit["decision"]
                picks = []
                for idx, p in enumerate(decision_dict.get("picks", [])):
                    # Old cache rows don't carry id/depends_on/bind — default safely
                    # so they run as independent parallel picks under the new scheduler.
                    picks.append(RoomPick(
                        id=p.get("id") or f"p{idx}",
                        gateway_id=p["gateway_id"],
                        sub_question=p["sub_question"],
                        depends_on=list(p.get("depends_on") or []),
                        bind=[dict(b) for b in (p.get("bind") or [])],
                    ))
                return (
                    RoutingDecision(
                        picks=picks,
                        decomposed=bool(decision_dict.get("decomposed", len(picks) > 1)),
                        rationale=f"routing_cache_hit: {decision_dict.get('rationale', '')}",
                    ),
                    meta,
                )

    # Selector call — the LLM decides and (sometimes) decomposes. Surfaced as
    # a single AGENT span; the prompt's decomposed=true bit gives us fan-out visibility.
    with tracing.span(
        "router.select",
        span_type="AGENT",
        inputs={"question": question, "active_members": [m["gateway_id"] for m in active]},
        attributes={
            "router_id": router_cfg["id"],
            "model": router_cfg.get("selector_model") or "default",
            "n_members": len(active),
        },
    ) as select_span:
        t0 = time.monotonic()
        decision = await select_rooms(
            question,
            active,
            token=token,
            databricks_host=_settings.databricks_host,
            model=router_cfg.get("selector_model"),
            system_prompt=router_cfg.get("selector_system_prompt"),
            hints=hints,
        )
        meta["selector_ms"] = int((time.monotonic() - t0) * 1000)
        select_span.set_outputs(decision.model_dump())

    # Persist (fire-and-forget), but only if we have an embedding and a pick — no point
    # caching the no-match / fallback cases.
    if (
        use_cache
        and router_cfg.get("routing_cache_enabled")
        and embedding is not None
        and decision.picks
        and not decision.rationale.startswith("selector failed")
    ):
        try:
            await _db.db_service.save_routing_cache(
                router_cfg["id"], question, embedding,
                decision.model_dump(), int(router_cfg.get("cache_ttl_hours") or 24),
            )
        except Exception as e:
            logger.warning("Routing cache save failed: %s", e)

    return decision, meta


_DISPATCH_POLL_TIMEOUT_S = 150.0
_DISPATCH_POLL_INTERVAL_S = 0.5


async def _poll_for_completion(msg_id: str, timeout_s: float = _DISPATCH_POLL_TIMEOUT_S) -> dict:
    """Wait for a synthetic gateway message to reach a terminal state.

    On cache miss, `_gateway_handle_query` returns synchronously with
    status=EXECUTING_QUERY and kicks off a background task that writes the
    final result (status=COMPLETED or FAILED) into `_gateway_synthetic_messages`.
    Polling that in-process dict lets us attach the actual SQL + row count
    to the router span (and return real results to the caller) instead of
    handing back a placeholder.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        stored = _gateway_synthetic_messages.get(msg_id)
        if stored:
            status = (stored.get("status") or "").upper()
            if status in ("FAILED", "CANCELLED"):
                return dict(stored)
            if status == "COMPLETED":
                # Race guard: the gateway's background task flips status→COMPLETED
                # BEFORE running execute_sql (so status polls see a valid terminal
                # state), and only populates _proxy.result after. Wait for the
                # _proxy.stage transition so `_proxy.result.data_array` is ready
                # for the DAG binder.
                proxy_stage = ((stored.get("_proxy") or {}).get("stage") or "").lower()
                if proxy_stage in ("completed", "failed", "cancelled", "cache_hit"):
                    return dict(stored)
        await asyncio.sleep(_DISPATCH_POLL_INTERVAL_S)
    return {
        "status": "FAILED",
        "error": {"error": f"router poll timeout after {int(timeout_s)}s", "type": "TIMEOUT"},
    }


async def _dispatch_pick(pick: RoomPick, token: str, identity: str) -> dict:
    """Call the gateway's _handle_query in-process, wait for completion, return the final result.

    Returns a uniform source-dict with {gateway_id, sub_question, status,
    response, error, elapsed_ms}. Polls the gateway's in-process synthetic-
    message store when the first call returns EXECUTING_QUERY (cache miss),
    so the span and the caller both see the completed SQL + row count.
    """
    with tracing.span(
        "gateway.query",
        span_type="CHAIN",
        inputs={"sub_question": pick.sub_question},
        attributes={"gateway_id": pick.gateway_id},
    ) as s:
        t0 = time.monotonic()
        try:
            gw = await _db.db_service.get_gateway(pick.gateway_id)
        except Exception as e:
            out = {
                "gateway_id": pick.gateway_id, "sub_question": pick.sub_question,
                "status": "FAILED", "response": None,
                "error": f"gateway lookup failed: {e}",
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            }
            s.set_outputs(_span_outputs_from_source(out))
            return out
        if not gw:
            out = {
                "gateway_id": pick.gateway_id, "sub_question": pick.sub_question,
                "status": "FAILED", "response": None,
                "error": f"gateway {pick.gateway_id} not found",
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            }
            s.set_outputs(_span_outputs_from_source(out))
            return out
        try:
            response = await _gateway_handle_query(
                space_id=gw["genie_space_id"],
                query_text=pick.sub_question,
                token=token,
                identity=identity,
                gateway=gw,
                auth_mode="user" if token else "service_principal",
            )
        except Exception as e:
            logger.exception("Router dispatch crashed for gateway=%s", pick.gateway_id)
            out = {
                "gateway_id": pick.gateway_id, "sub_question": pick.sub_question,
                "status": "FAILED", "response": None,
                "error": f"dispatch crashed: {e}",
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            }
            s.set_outputs(_span_outputs_from_source(out))
            return out

        # Cache miss returns EXECUTING_QUERY + a synthetic msg_id; poll in-process
        # until the background task writes the terminal status. Cache hit is already
        # terminal at this point so the poll short-circuits.
        status = (response.get("status") or "").upper()
        msg_id = response.get("message_id") or ""
        if status == "EXECUTING_QUERY" and msg_id.startswith(_GATEWAY_MSG_PREFIX):
            final = await _poll_for_completion(msg_id)
            # _poll_for_completion returns the final synthetic-message record. Merge
            # back into `response` keeping the conversation/message ids from the
            # initial handoff.
            response = {**response, **final}
        elif msg_id.startswith(_GATEWAY_MSG_PREFIX):
            # Cache hit: _handle_query returned a stripped response (no `_proxy`).
            # Re-read the unstripped synthetic-message record so the DAG binder
            # can see `_proxy.result.data_array` for upstream value extraction.
            stored = _gateway_synthetic_messages.get(msg_id)
            if stored:
                response = {**response, "_proxy": stored.get("_proxy")}

        final_status = (response.get("status") or "UNKNOWN").upper()
        err = response.get("error")
        out = {
            "gateway_id": pick.gateway_id,
            "sub_question": pick.sub_question,
            "status": final_status,
            "response": response,
            "error": (err.get("error") if isinstance(err, dict) else err) if err else None,
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
        }
        s.set_outputs(_span_outputs_from_source(out))
        return out


def _span_outputs_from_source(source: dict) -> dict:
    """Attach a rich but bounded result payload to the gateway.query span.

    Full response can be large (SQL result rows), so we trim:
    - sql: the full SQL text (essential for debugging + eval scoring)
    - row_count, column_count: the result shape
    - from_cache: was this served by the semantic cache
    - sample_rows: up to 5 rows for visual verification; guarded by length so a
      pathological row doesn't balloon the span
    """
    resp = source.get("response") or {}
    attachments = resp.get("attachments") or []
    sql = None
    row_count = None
    column_count = None
    sample_rows = None
    from_cache = False

    for a in attachments:
        q = a.get("query") or {}
        if isinstance(q, dict):
            if sql is None and isinstance(q.get("query"), str):
                sql = q["query"]
            meta = q.get("query_result_metadata") or {}
            if row_count is None and "row_count" in meta:
                row_count = meta["row_count"]
            if column_count is None and "column_count" in meta:
                column_count = meta["column_count"]
        text = (a.get("text") or {}).get("content") or ""
        if "served from the semantic cache" in text.lower():
            from_cache = True

    # Gateway also surfaces inline result rows on `result` for COMPLETED responses.
    # The shape is { "data_array": [[...], ...], "schema": {...}, "row_count": N } or
    # a statement_response. Keep up to 5 rows trimmed to 200 chars per cell.
    result = resp.get("result") or {}
    data_array = None
    if isinstance(result, dict):
        data_array = result.get("data_array")
        if row_count is None:
            row_count = result.get("row_count") or result.get("total_row_count")
    if isinstance(data_array, list) and data_array:
        capped = []
        for row in data_array[:5]:
            if isinstance(row, (list, tuple)):
                capped.append([_cap(cell) for cell in row])
            else:
                capped.append(_cap(row))
        sample_rows = capped

    return {
        "status": source.get("status"),
        "sql": _cap(sql, 4000) if sql else None,
        "row_count": row_count,
        "column_count": column_count,
        "from_cache": from_cache,
        "sample_rows": sample_rows,
        "error": source.get("error"),
        "elapsed_ms": source.get("elapsed_ms"),
    }


def _cap(value, limit: int = 200):
    """Truncate a value to `limit` chars when rendered as a string.

    Keeps span payload bounded without losing type info for small values.
    """
    if value is None:
        return None
    s = value if isinstance(value, str) else str(value)
    if len(s) <= limit:
        return value if isinstance(value, str) or not isinstance(value, (int, float, bool)) else value
    return s[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# DAG scheduler + binding (Route A)
# ---------------------------------------------------------------------------

_BIND_MAX_VALUES = 200


def _topological_stages(picks: list[RoomPick]) -> list[list[RoomPick]]:
    """Group picks into dependency-respecting stages.

    Returns a list of stages; each stage is a list of picks whose `depends_on`
    is satisfied by earlier stages. On cycle (shouldn't happen — selector
    validates forward-refs — but defend anyway), logs and returns everything as
    a single flat stage with deps stripped.
    """
    if not picks:
        return []
    by_id = {p.id: p for p in picks if p.id}
    # Filter to real deps (already validated in selector, but double-guard).
    remaining = dict(by_id)
    stages: list[list[RoomPick]] = []
    done: set[str] = set()
    while remaining:
        ready = [p for p in remaining.values() if all(d in done for d in p.depends_on)]
        if not ready:
            logger.warning(
                "Router DAG cycle or missing upstream in picks=%s — flattening to parallel",
                [p.id for p in picks],
            )
            flat = [
                RoomPick(id=p.id, gateway_id=p.gateway_id, sub_question=p.sub_question)
                for p in picks
            ]
            return [flat]
        # Stable order (selector ordinal) within a stage.
        ready.sort(key=lambda p: list(by_id.keys()).index(p.id))
        stages.append(ready)
        for p in ready:
            done.add(p.id)
            del remaining[p.id]
    return stages


def _result_view(result_response: dict) -> dict:
    """Return the best available `result` view inside a gateway response.

    The clone API returns results under `response.result` OR under the router-
    internal `response._proxy.result`. Prefer an object that has schema+data,
    falling back to whichever is a dict.
    """
    if not isinstance(result_response, dict):
        return {}
    candidates = []
    direct = result_response.get("result")
    proxy = (result_response.get("_proxy") or {}).get("result") if isinstance(result_response.get("_proxy"), dict) else None
    for c in (direct, proxy):
        if isinstance(c, dict):
            candidates.append(c)
    # Prefer a candidate that has both schema AND data_array.
    for c in candidates:
        if (c.get("schema") or {}).get("columns") and isinstance(c.get("data_array"), list):
            return c
    for c in candidates:
        if isinstance(c.get("data_array"), list):
            return c
    return candidates[0] if candidates else {}


def _column_names_from_result(result: dict) -> list[str]:
    """Normalize the variety of column-schema shapes the gateway uses.

    Shapes observed in prod:
    - `result.columns = ["Project", "net_disbursement_usd"]`   (flat strings)
    - `result.columns = [{"name": "project_id", ...}, ...]`     (list of dicts)
    - `result.schema.columns = [{"name": "...", ...}, ...]`     (DBSQL classic)
    - `result.manifest.schema.columns = [...]`                  (statement-exec)
    """
    if not isinstance(result, dict):
        return []
    # Direct flat or dict list on result.columns
    cols = result.get("columns")
    if isinstance(cols, list) and cols:
        out = []
        for c in cols:
            if isinstance(c, str):
                out.append(c)
            elif isinstance(c, dict):
                name = c.get("name") or c.get("column_name")
                if isinstance(name, str):
                    out.append(name)
        if out:
            return out
    # schema.columns shape
    schema_cols = (result.get("schema") or {}).get("columns") or []
    out = [c.get("name") for c in schema_cols if isinstance(c, dict) and c.get("name")]
    if out:
        return out
    # manifest.schema.columns shape
    manifest_cols = ((result.get("manifest") or {}).get("schema") or {}).get("columns") or []
    out = [c.get("name") for c in manifest_cols if isinstance(c, dict) and c.get("name")]
    return out


# Re-exports for backward-compatible local references; canonical source is
# services/column_match.py (also used by the cache-write validator).
from app.services.column_match import (
    METRIC_SUFFIXES as _METRIC_SUFFIXES,
    TARGET_STRIP_SUFFIXES as _TARGET_STRIP_SUFFIXES,
    norm as _norm,
    is_metric_column as _is_metric_column,
    target_stems as _target_stems,
    fuzzy_column_match as _fuzzy_column_match,
)


def _find_column_index(result_response: dict, column: str) -> tuple[int | None, list[str] | None, str]:
    """Locate a column in a gateway response and return (index, column_names, reason_if_failed).

    The `result` object may live on `response.result` OR the router-only
    `response._proxy.result` — see `_result_view`. Columns may be flat strings
    or dicts — see `_column_names_from_result`.

    Resolution order:
    1. Exact match (case-insensitive)
    2. Fuzzy match (strip `_id` suffix; substring)
    3. Single-column fallback
    """
    result = _result_view(result_response)
    col_names = _column_names_from_result(result)

    # Secondary fallback: dig for columns on first attachment query_result_metadata.
    if not col_names:
        for a in (result_response.get("attachments") or []):
            q = a.get("query") or {}
            meta = q.get("query_result_metadata") or {}
            maybe = meta.get("columns") or meta.get("column_names") or []
            if isinstance(maybe, list) and maybe:
                col_names = [c.get("name") if isinstance(c, dict) else str(c) for c in maybe]
                break

    if not col_names:
        return None, None, "no_column_schema"

    idx = _fuzzy_column_match(column, col_names)
    if idx is not None:
        return idx, col_names, ""
    # Single-column fallback (last resort).
    if len(col_names) == 1:
        return 0, col_names, ""
    return None, col_names, "column_not_found"


def _extract_bound_values(result_response: dict, column: str, reducer: str) -> tuple[list[str], str]:
    """Extract values from an upstream gateway response.

    Returns (values, failure_reason). `failure_reason` is empty on success.
    - reducer="list"     → distinct values preserving order, cap 200
    - reducer="scalar"   → first value only
    - reducer="first_n"  → treat as list today; N caps at 200

    Gateway result rows live at `result.data_array` (or `_proxy.result.data_array`
    for router-internal dispatches; see `_result_view`). Each row is a list of
    cells positioned by `result.schema.columns`. Cells may be strings, numbers,
    bools, or None — we stringify for natural-language substitution.
    """
    result = _result_view(result_response)
    data_array = result.get("data_array")
    if not isinstance(data_array, list):
        return [], "no_data_array"
    if not data_array:
        return [], "upstream_empty"

    col_idx, _, reason = _find_column_index(result_response, column)
    if col_idx is None:
        return [], reason or "column_not_found"

    seen: set[str] = set()
    values: list[str] = []
    for row in data_array:
        if not isinstance(row, (list, tuple)) or col_idx >= len(row):
            continue
        cell = row[col_idx]
        if cell is None:
            continue
        s = cell if isinstance(cell, str) else str(cell)
        if s in seen:
            continue
        seen.add(s)
        values.append(s)
        if reducer == "scalar":
            break
        if len(values) >= _BIND_MAX_VALUES:
            break

    if not values:
        return [], "upstream_empty"
    return values, ""


def _render_sub_question(
    pick: RoomPick,
    results_by_id: dict[str, dict],
) -> tuple[str | None, dict]:
    """Substitute `{{placeholder}}` tokens in pick.sub_question using upstream results.

    Returns (rendered_sub_question, diagnostics).
    - On any bind failure returns (None, {failure_reason, placeholder, upstream, column, reducer}).
    - On success returns (rendered_text, {placeholder: {column, reducer, n_values, sample_values}, ...}).
    """
    if not pick.bind:
        return pick.sub_question, {}

    rendered = pick.sub_question
    diag: dict[str, Any] = {}
    for b in pick.bind:
        placeholder = b.get("placeholder")
        upstream = b.get("upstream")
        column = b.get("column")
        reducer = b.get("reducer") or "list"
        upstream_result = results_by_id.get(upstream)
        if not upstream_result:
            return None, {
                "failure_reason": "upstream_missing",
                "placeholder": placeholder,
                "upstream": upstream,
                "column": column,
                "reducer": reducer,
            }
        if (upstream_result.get("status") or "").upper() != "COMPLETED":
            return None, {
                "failure_reason": "upstream_failed",
                "placeholder": placeholder,
                "upstream": upstream,
                "column": column,
                "reducer": reducer,
            }
        response = upstream_result.get("response") or {}
        values, reason = _extract_bound_values(response, column, reducer)
        if reason:
            return None, {
                "failure_reason": reason,
                "placeholder": placeholder,
                "upstream": upstream,
                "column": column,
                "reducer": reducer,
            }
        rendered_values = ", ".join(values)
        rendered = rendered.replace("{{" + placeholder + "}}", rendered_values)
        diag[placeholder] = {
            "upstream": upstream,
            "column": column,
            "reducer": reducer,
            "n_values": len(values),
            "sample_values": values[:10],
        }

    return rendered, diag


def _skipped_source(pick: RoomPick, stage_index: int, failure_reason: str, bind_diag: dict | None = None) -> dict:
    """Build a uniform source dict for a pick that never dispatched."""
    return {
        "gateway_id": pick.gateway_id,
        "sub_question": pick.sub_question,
        "pick_id": pick.id,
        "depends_on": list(pick.depends_on),
        "stage_index": stage_index,
        "bound_sub_question": None,
        "bind_diagnostics": bind_diag or {"failure_reason": failure_reason},
        "status": "SKIPPED",
        "response": None,
        "error": failure_reason,
        "elapsed_ms": 0,
    }


async def _execute_dag(
    picks: list[RoomPick],
    token: str,
    identity: str,
) -> tuple[list[dict], dict]:
    """Run the decomposed plan as a DAG, resolving bindings between stages.

    Returns (sources, stats). Sources are in original-picks order; stats includes
    n_stages, n_skipped_upstream_failed, n_skipped_binding_failed.
    """
    stages = _topological_stages(picks)
    results_by_id: dict[str, dict] = {}
    stats = {
        "n_stages": len(stages),
        "n_skipped_upstream_failed": 0,
        "n_skipped_binding_failed": 0,
    }

    # Build the final sources list in original pick order, so the response
    # reads the way the selector planned it regardless of stage grouping.
    source_by_id: dict[str, dict] = {}

    for stage_index, stage in enumerate(stages):
        with tracing.span(
            "router.stage",
            span_type="CHAIN",
            inputs={"pick_ids": [p.id for p in stage]},
            attributes={"stage_index": stage_index, "n_picks": len(stage)},
        ) as stage_span:
            ready: list[tuple[RoomPick, str, dict]] = []  # (pick, rendered_sub_question, bind_diag)
            for p in stage:
                if p.depends_on and any(
                    (results_by_id.get(u) or {}).get("status") != "COMPLETED"
                    for u in p.depends_on
                ):
                    skipped = _skipped_source(p, stage_index, "upstream_failed")
                    results_by_id[p.id] = skipped
                    source_by_id[p.id] = skipped
                    stats["n_skipped_upstream_failed"] += 1
                    continue
                if p.bind:
                    with tracing.span(
                        "router.bind",
                        span_type="RETRIEVER",
                        inputs={
                            "pick_id": p.id,
                            "depends_on": list(p.depends_on),
                            "bind": p.bind,
                        },
                    ) as bind_span:
                        rendered, diag = _render_sub_question(p, results_by_id)
                        bind_span.set_outputs({"diagnostics": diag, "rendered_len": len(rendered) if rendered else 0})
                else:
                    rendered, diag = p.sub_question, {}
                if rendered is None:
                    skipped = _skipped_source(p, stage_index, diag.get("failure_reason", "bind_failed"), diag)
                    results_by_id[p.id] = skipped
                    source_by_id[p.id] = skipped
                    stats["n_skipped_binding_failed"] += 1
                    continue
                ready.append((p, rendered, diag))

            if ready:
                dispatch_results = await asyncio.gather(*(
                    _dispatch_pick(
                        RoomPick(
                            id=p.id,
                            gateway_id=p.gateway_id,
                            sub_question=rendered,
                            depends_on=list(p.depends_on),
                            bind=p.bind,
                        ),
                        token,
                        identity,
                    )
                    for (p, rendered, _diag) in ready
                ))
                for (p, rendered, diag), r in zip(ready, dispatch_results):
                    r["pick_id"] = p.id
                    r["depends_on"] = list(p.depends_on)
                    r["stage_index"] = stage_index
                    r["bound_sub_question"] = rendered
                    r["bind_diagnostics"] = diag
                    results_by_id[p.id] = r
                    source_by_id[p.id] = r

            stage_span.set_outputs({
                "n_dispatched": len(ready),
                "n_skipped": len(stage) - len(ready),
            })

    ordered_sources = [source_by_id[p.id] for p in picks if p.id in source_by_id]
    return ordered_sources, stats


@router_router.post("/routers/{router_id}/preview")
async def preview_routing(router_id: str, body: RouterQueryRequest, req: Request):
    """Return the routing decision without dispatching. Used by the Preview tab
    to iterate on catalog metadata without spending warehouse time."""
    await require_role(req, "use")
    try:
        router_cfg = await _db.db_service.get_router(router_id, include_members=True)
        if not router_cfg:
            raise HTTPException(status_code=404, detail="Router not found")

        token = resolve_user_token_optional(req)
        identity = req.headers.get("X-Forwarded-Email") or "api-user"

        with tracing.span(
            "router.preview",
            span_type="AGENT",
            inputs={"question": body.question, "hints": body.hints},
            attributes={
                "router_id": router_id,
                "user_identity": identity,
                "mode": "preview",
            },
        ) as root:
            t0 = time.monotonic()
            decision, meta = await _resolve_decision(
                router_cfg, body.question, body.hints, token, use_cache=False,
            )
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            root.set_outputs({
                "n_picks": len(decision.picks),
                "decomposed": decision.decomposed,
                "rationale": decision.rationale,
                "elapsed_ms": elapsed_ms,
            })
            trace_id = tracing.current_trace_id()

        return {
            "router_id": router_id,
            "question": body.question,
            "routing": decision.model_dump(),
            "diagnostics": meta,
            "elapsed_ms": elapsed_ms,
            "trace_id": trace_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in router preview")
        raise HTTPException(status_code=500, detail=str(e))


@router_router.post("/routers/{router_id}/query")
async def router_query(router_id: str, body: RouterQueryRequest, req: Request):
    """Decompose + select + dispatch. Fans out to each picked gateway in parallel."""
    await require_role(req, "use")
    try:
        router_cfg = await _db.db_service.get_router(router_id, include_members=True)
        if not router_cfg:
            raise HTTPException(status_code=404, detail="Router not found")

        token = resolve_user_token_optional(req)
        identity = req.headers.get("X-Forwarded-Email") or "api-user"

        with tracing.span(
            "router.query",
            span_type="AGENT",
            inputs={"question": body.question, "hints": body.hints},
            attributes={
                "router_id": router_id,
                "user_identity": identity,
                "mode": "query",
            },
        ) as root:
            t0 = time.monotonic()
            decision, meta = await _resolve_decision(
                router_cfg, body.question, body.hints, token, use_cache=True,
            )

            if not decision.picks:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                root.set_outputs({
                    "n_picks": 0,
                    "decomposed": decision.decomposed,
                    "rationale": decision.rationale,
                    "elapsed_ms": elapsed_ms,
                })
                trace_id = tracing.current_trace_id()
                return {
                    "router_id": router_id,
                    "question": body.question,
                    "routing": decision.model_dump(),
                    "diagnostics": meta,
                    "sources": [],
                    "elapsed_ms": elapsed_ms,
                    "trace_id": trace_id,
                }

            # Execute the plan as a DAG — independent picks in parallel per stage,
            # dependent picks run after their upstreams with bindings rendered.
            results, dag_stats = await _execute_dag(decision.picks, token, identity)

            elapsed_ms = int((time.monotonic() - t0) * 1000)
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

        return {
            "router_id": router_id,
            "question": body.question,
            "routing": decision.model_dump(),
            "diagnostics": {**meta, **dag_stats},
            "sources": results,
            "elapsed_ms": elapsed_ms,
            "trace_id": trace_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in router query")
        raise HTTPException(status_code=500, detail=str(e))
