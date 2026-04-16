# Proxy API Wraps Clone API — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the duplicate query processing path by making `/api/v1/query` a thin adapter over `_handle_query` from the Clone API, keeping zero frontend changes and zero changes to the Clone API's external contract.

**Architecture:** The Clone API (`genie_clone_routes.py`) keeps `_handle_query` as the single processing path. Its `_synthetic_messages` store is enriched with proxy-needed fields (`stage`, `from_cache`, `sql_query`, `result`). `routes.py` maps gateway → `_handle_query` → stores `query_id → msg_id` in a local registry, then translates `_synthetic_messages` reads back to `QueryStatus`. `query_processor.py` and its queue-based processing become dead code, removed.

**Tech Stack:** Python, FastAPI, asyncio — no new dependencies.

---

## File Map

| File | Change |
|------|--------|
| `backend/app/api/genie_clone_routes.py` | Enrich `_synthetic_messages` entries with `stage`, `from_cache`, `sql_query`, `result`; add stage updates in background task; export `_synthetic_messages` and `_handle_query` |
| `backend/app/api/routes.py` | Replace `query_processor.submit_query` with `_handle_query` call; replace `queue_service.get_query_status` with `_synthetic_messages` read + translation |
| `backend/app/services/query_processor.py` | Delete |
| `backend/app/services/queue_service.py` | Delete |

---

## Task 1: Enrich `_synthetic_messages` — cache hit path

**File:** `backend/app/api/genie_clone_routes.py`

In `_handle_query`, the cache hit branch stores response in `_synthetic_messages[msg_id]`. Add proxy fields to this dict so the status adapter can read them without parsing Genie attachment format.

- [ ] **Step 1: Locate the cache hit store in `_handle_query`**

Line ~355:
```python
_synthetic_messages[msg_id] = response
_synthetic_messages[att_id] = {"sql_query": sql_query, "token": token, "space_id": space_id}
```

- [ ] **Step 2: Add proxy fields to the response before storing**

Replace those two lines with:
```python
response["_proxy"] = {
    "stage": "completed",
    "from_cache": True,
    "sql_query": sql_query,
    "result": sql_result,
}
_synthetic_messages[msg_id] = response
_synthetic_messages[att_id] = {"sql_query": sql_query, "token": token, "space_id": space_id}
```

- [ ] **Step 3: Commit**
```bash
git add backend/app/api/genie_clone_routes.py
git commit -m "feat: add _proxy metadata to synthetic messages for cache hit"
```

---

## Task 2: Enrich `_synthetic_messages` — cache miss intermediate stages

**File:** `backend/app/api/genie_clone_routes.py`

The cache miss path sets `_synthetic_messages[msg_id]` to EXECUTING_QUERY and spawns a background task. The status adapter needs to see stage transitions as the background task runs.

- [ ] **Step 1: Add `_proxy` to the initial EXECUTING_QUERY store**

In `_handle_query`, the miss path (line ~362):
```python
response = _format_executing_response(conv_id, msg_id)
_synthetic_messages[msg_id] = response
```

Change to:
```python
response = _format_executing_response(conv_id, msg_id)
response["_proxy"] = {"stage": "cache_miss", "from_cache": False, "sql_query": None, "result": None}
_synthetic_messages[msg_id] = response
```

- [ ] **Step 2: Add `processing_genie` stage update at background task start**

In `_process_genie_background`, after the rate-limit wait loop exits (just before the first Genie call, ~line 199), add:
```python
if msg_id in _synthetic_messages:
    _synthetic_messages[msg_id].setdefault("_proxy", {})["stage"] = "processing_genie"
```

- [ ] **Step 3: Add `completed` with result on success**

In `_process_genie_background`, after the successful `COMPLETED` branch saves to cache (line ~233, just before `return`):

First call `execute_sql` to get tabular result:
```python
actual_result = None
if sql_query:
    try:
        sql_exec = await genie_service.execute_sql(sql_query, rs)
        if sql_exec.get("status") == "SUCCEEDED":
            actual_result = sql_exec.get("result")
    except Exception as e:
        logger.warning("execute_sql after cache miss failed: %s", e)
```

Then update `_synthetic_messages[msg_id]` before the existing `return`:
```python
_synthetic_messages[msg_id]["_proxy"] = {
    "stage": "completed",
    "from_cache": False,
    "sql_query": sql_query,
    "result": actual_result,
}
```

- [ ] **Step 4: Add `failed` stage on all failure paths**

At the end of `_process_genie_background` where FAILED is set (~line 241 non-COMPLETED, ~line 267 retries exhausted), add `_proxy` to each:

Non-COMPLETED terminal:
```python
_synthetic_messages[msg_id] = {
    ...,
    "_proxy": {"stage": "failed", "from_cache": False, "sql_query": None, "result": None},
}
```

Retries exhausted:
```python
_synthetic_messages[msg_id] = {
    ...,
    "_proxy": {"stage": "failed", "from_cache": False, "sql_query": None, "result": None},
}
```

- [ ] **Step 5: Commit**
```bash
git add backend/app/api/genie_clone_routes.py
git commit -m "feat: track pipeline stages in _synthetic_messages for proxy adapter"
```

---

## Task 3: Rewrite `routes.py` submit_query and get_query_status

**File:** `backend/app/api/routes.py`

Replace the `query_processor` calls with direct `_handle_query` calls. Add a module-level `_proxy_registry: dict[str, str]` mapping `query_id → msg_id`.

- [ ] **Step 1: Add imports and registry**

At the top of `routes.py`, replace the `query_processor` and `queue_service` imports with:
```python
import uuid
from app.api.genie_clone_routes import _handle_query, _synthetic_messages

_proxy_registry: dict[str, str] = {}
```

Remove:
```python
from app.services.query_processor import query_processor
from app.services.queue_service import queue_service
```

- [ ] **Step 2: Rewrite `submit_query`**

Replace the entire `submit_query` function body:
```python
@router.post("/query", response_model=QueryResponse)
async def submit_query(request: QueryRequest, req: Request):
    try:
        token = req.headers.get("X-Forwarded-Access-Token") or ""
        identity = req.headers.get("X-Forwarded-Email") or ""

        if not identity:
            raise HTTPException(status_code=401, detail="X-Forwarded-Email header missing.")

        # Resolve gateway
        gateway = None
        space_id = request.config.genie_space_id if request.config else None
        if space_id:
            try:
                gw = await _db.db_service.get_gateway(space_id)
                if gw:
                    gateway = gw
                    space_id = gw["genie_space_id"]
            except Exception:
                pass

        if not space_id:
            raise HTTPException(status_code=400, detail="No gateway or space_id provided.")

        result = await _handle_query(
            space_id=space_id,
            query_text=request.query,
            token=token,
            identity=identity,
            gateway=gateway,
        )

        query_id = str(uuid.uuid4())
        msg_id = result.get("message_id")
        _proxy_registry[query_id] = msg_id

        return QueryResponse(query_id=query_id, stage=QueryStage.RECEIVED, message="Query submitted successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error submitting query")
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 3: Rewrite `get_query_status_post`**

Replace the `get_query_status_post` function:
```python
@router.post("/query/{query_id}/status", response_model=QueryStatus)
async def get_query_status_post(query_id: str, request: Optional[StatusRequest] = None):
    msg_id = _proxy_registry.get(query_id)
    if not msg_id:
        raise HTTPException(status_code=404, detail=f"Query {query_id} not found")

    msg = _synthetic_messages.get(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail=f"Query {query_id} not found")

    proxy = msg.get("_proxy", {})
    stage_str = proxy.get("stage", "received")
    from_cache = proxy.get("from_cache", False)
    sql_query = proxy.get("sql_query")
    result = proxy.get("result")
    error = msg.get("error")

    _stage_map = {
        "received":         QueryStage.RECEIVED,
        "checking_cache":   QueryStage.CHECKING_CACHE,
        "cache_hit":        QueryStage.CACHE_HIT,
        "cache_miss":       QueryStage.CACHE_MISS,
        "processing_genie": QueryStage.PROCESSING_GENIE,
        "executing_sql":    QueryStage.EXECUTING_SQL,
        "completed":        QueryStage.COMPLETED,
        "failed":           QueryStage.FAILED,
    }
    stage = _stage_map.get(stage_str, QueryStage.RECEIVED)

    return QueryStatus(
        query_id=query_id,
        stage=stage,
        from_cache=from_cache,
        sql_query=sql_query,
        result=result,
        error=str(error) if error else None,
    )
```

- [ ] **Step 4: Remove unused imports from routes.py**

Remove `RuntimeSettings`, `queue_service`, `query_processor` imports. Keep `_db`, `QueryStage`, `QueryStatus`, `QueryResponse`, `QueryRequest`, `RuntimeConfig`.

- [ ] **Step 5: Commit**
```bash
git add backend/app/api/routes.py
git commit -m "refactor: proxy API wraps Clone API _handle_query, removes query_processor dependency"
```

---

## Task 4: Delete dead code

- [ ] **Step 1: Delete `query_processor.py` and `queue_service.py`**
```bash
rm backend/app/services/query_processor.py
rm backend/app/services/queue_service.py
```

- [ ] **Step 2: Remove any remaining imports of these modules**

Search and remove:
```bash
grep -r "query_processor\|queue_service" backend/ --include="*.py" -l
```

Fix any remaining references (likely `main.py` startup code).

- [ ] **Step 3: Commit**
```bash
git add -A
git commit -m "chore: remove query_processor and queue_service (replaced by Clone API path)"
```

---

## Task 5: Smoke test

- [ ] **Step 1: Start backend locally**
```bash
cd backend && python -m uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 2: Submit a query via Proxy API**
```bash
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -H "X-Forwarded-Email: test@test.com" \
  -d '{"query": "how many orders?", "config": {"genie_space_id": "<gateway_id>", "storage_backend": "lakebase"}}' | jq .
# Expected: { "query_id": "...", "stage": "received" }
```

- [ ] **Step 3: Poll status**
```bash
curl -s -X POST http://localhost:8000/api/query/<query_id>/status \
  -H "Content-Type: application/json" \
  -d '{}' | jq .
# Expected: { "stage": "cache_miss" | "processing_genie" | "completed", "from_cache": false/true, ... }
```

- [ ] **Step 4: Verify Clone API still works unchanged**
```bash
curl -s -X POST http://localhost:8000/api/2.0/genie/spaces/<gateway_id>/start-conversation \
  -H "Authorization: Bearer <token>" \
  -d '{"content": "how many orders?"}' | jq .
# Expected: Genie-format response, unchanged
```

- [ ] **Step 5: Push branch and open PR**
```bash
git push origin fix/gateway-normalization-validation-flags
# (or create a new branch if needed)
```
