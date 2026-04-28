"""Router selector service — picks gateway(s) for a question.

Given a question and a list of router members (each with catalog metadata),
calls an FMAPI LLM to decide which member handles the query. If the question
contains multiple independent intents, the LLM can decompose it into a set of
(gateway_id, sub_question) picks.

Follows the canonical FMAPI call pattern from `question_normalizer`: build a
WorkspaceClient with the caller's token, POST to
`/serving-endpoints/{endpoint}/invocations`.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

logger = logging.getLogger(__name__)

# Default FMAPI endpoint used by the selector; overridable per-router.
SELECTOR_DEFAULT_ENDPOINT = "databricks-llama-4-maverick"

_SYSTEM_PROMPT_DEFAULT = """You route natural-language data questions to the right data room(s).

You are given a catalog of rooms and a user question. Respond with a single json object matching this schema:

  {"picks": [
     {"id": "p0",
      "gateway_id": "...",
      "sub_question": "...",
      "depends_on": [],
      "bind": []},
     ...
   ],
   "decomposed": <bool>,
   "rationale": "<one short sentence>"}

Rules:
- Pick the smallest set of rooms that can answer the question.
- If the question is single-intent, return exactly ONE pick with depends_on=[] and decomposed=false.
- If the question has multiple independent intents that no single room covers, split it into picks — one per room — and set decomposed=true.
- Every pick has a unique id like "p0", "p1" (use these ids in depends_on references).

Independent picks (depends_on=[]):
- sub_question must be a complete standalone question (no pronouns referring to other picks, no "and also" linking). The downstream room will not see sibling picks.

Dependent picks (depends_on non-empty) — use ONLY when a pick genuinely needs values produced by an upstream pick:
- Each listed id in depends_on MUST be the id of an earlier pick in the same response.
- sub_question must contain one {{placeholder}} token per bind entry (double braces, alphanumeric+underscore name).
- Each bind entry specifies how to fill its placeholder from an upstream pick's SQL result:
    {"placeholder": "donor_ids",
     "upstream": "p0",           // a pick id that appears in this pick's depends_on
     "column": "donor_id",       // the column to extract from the upstream result
     "reducer": "list"}          // one of: "list" (v1), "scalar", "first_n"
- **CRITICAL: the upstream pick's sub_question MUST explicitly instruct the room to return just the bound column** (usually one id per row). Example upstream sub_question: "List ONLY the donor_id for the top 5 donors by FY2024 pledge amount — no other columns." Otherwise the room may return display names or aggregates instead, and binding will fail.
- Prefer short, scalar-id columns for bind.column (e.g. donor_id, project_id, trust_fund_id) — never attempt to bind rows of metrics or names.
- The downstream sub_question should read naturally after string substitution, e.g. "Show gift history for donors {{donor_ids}}."
- DO NOT create a dependency if a single room can answer the whole question. Dependencies cost latency and reduce cache reuse.
- DO NOT create dependencies more than 3 stages deep.
- Consider carefully: if a downstream pick needs BOTH values from an upstream (e.g. trust_fund_ids) AND also needs to compute something else (e.g. theme mix), do NOT collapse both into one upstream — either (a) have the upstream return ONLY the ids, with a separate stage for any aggregation, or (b) move the aggregation into the downstream pick.

Other rules:
- If NO room matches, return picks=[] with a rationale explaining why.
- Never invent a gateway_id that is not in the catalog.
- Rationale is for debugging; keep it under 25 words.
- Output valid json only — no prose, no markdown, no code fences.

DAG SHAPE — fan-out vs. chain (decisive for multi-stage questions):
- FAN-OUT (parallel) when downstream picks compute INDEPENDENT properties of the SAME upstream entity. Phrasing cues: "X and Y of those Z", "Z's X AND Z's Y" — both X and Y branch directly from Z. Both downstream picks `depends_on` the same upstream and bind on the same column.
- CHAIN (sequential) when a downstream pick filters on an INTERMEDIATE result, NOT the topmost upstream. Phrasing cues: "X of those Y" where Y was itself derived from a prior pick, or "X of/from/for Y of/from/for Z" (object types stack). Do NOT collapse this into fan-out from Z — the intermediate Y is what filters X. Build a 3-stage chain Z→Y→X.
- MINIMIZE stages: use the fewest hops needed. If a single room can join through its own schema natively (e.g. a donor-relations room can join donor→TF→grant inside its own SQL), do NOT insert bridging picks — let the room do the join.
- DEFAULT to fan-out when in doubt, since chains serialize execution and cost latency. Only chain when the transitive-dependency phrasing is unambiguous.

BIND-COLUMN selection:
- The bind column must be one the DOWNSTREAM room can filter on, not just one the upstream produces. Use room titles as a guide: project-centric rooms (procurement, safeguards, disbursements, results, project portfolio) all bind on `project_id`; trust-fund-centric rooms bind on `trust_fund_id`; donor-centric rooms bind on `donor_id`. When the upstream has multiple ids available (e.g. procurement has both `contract_id` and `project_id`), pick the one the downstream actually filters on.
- Restate as a sub-question constraint: the upstream sub_question must list the column that the downstream binds on. If the downstream binds on `project_id`, the upstream MUST return `project_id` (even if the upstream's natural primary key is something else).

Examples:

# Example 1 — single-intent, one pick
{"picks": [
   {"id": "p0", "gateway_id": "gw_donors", "sub_question": "What is the total pledge amount in FY2024?", "depends_on": [], "bind": []}
 ],
 "decomposed": false,
 "rationale": "Single donor aggregate — gw_donors covers it."}

# Example 2 — independent intents, two parallel picks
{"picks": [
   {"id": "p0", "gateway_id": "gw_donors", "sub_question": "How many active donors are there?", "depends_on": [], "bind": []},
   {"id": "p1", "gateway_id": "gw_projects", "sub_question": "How many active projects are there?", "depends_on": [], "bind": []}
 ],
 "decomposed": true,
 "rationale": "Two unrelated counts — one per room."}

# Example 3 — dependent chain: find ids (ONLY the ids), then use them downstream
{"picks": [
   {"id": "p0", "gateway_id": "gw_donors",
    "sub_question": "List ONLY the donor_id for the top 5 donors by FY2024 pledge amount — return just donor_id, no other columns.",
    "depends_on": [], "bind": []},
   {"id": "p1", "gateway_id": "gw_projects",
    "sub_question": "Show project allocations for donors {{donor_ids}}.",
    "depends_on": ["p0"],
    "bind": [{"placeholder": "donor_ids", "upstream": "p0", "column": "donor_id", "reducer": "list"}]}
 ],
 "decomposed": true,
 "rationale": "p0 finds donor ids; p1 consumes them to fetch project allocations."}

# Example 4 — CHAIN through an intermediate (transitive dependency)
# Question: "For top-quartile Foundation donors, what's the theme mix of the trust funds they fund, and the disbursement ratio of THOSE FUNDS' grants?"
# "those funds' grants" = grants of the TFs found in p1, not grants of donors directly. So 3-stage chain, NOT fan-out from donors.
{"picks": [
   {"id": "p0", "gateway_id": "gw_donors",
    "sub_question": "List ONLY the donor_id for top-quartile Foundation donors by received_usd — return just donor_id, no other columns.",
    "depends_on": [], "bind": []},
   {"id": "p1", "gateway_id": "gw_trust_funds",
    "sub_question": "List ONLY the trust_fund_id with primary_theme for trust funds funded by donors {{donor_ids}} — return just trust_fund_id and primary_theme.",
    "depends_on": ["p0"],
    "bind": [{"placeholder": "donor_ids", "upstream": "p0", "column": "donor_id", "reducer": "list"}]},
   {"id": "p2", "gateway_id": "gw_grants",
    "sub_question": "Disbursement ratio of grants for trust funds {{trust_fund_ids}}.",
    "depends_on": ["p1"],
    "bind": [{"placeholder": "trust_fund_ids", "upstream": "p1", "column": "trust_fund_id", "reducer": "list"}]}
 ],
 "decomposed": true,
 "rationale": "Chain donors→TFs→grants because 'those funds' refers to p1's TFs."}

# Example 5 — FAN-OUT: parallel independent intents from one upstream
# Question: "FCV-country projects approved in FY2022 that had a safeguard category upgrade AND ≥1 contract cancellation."
# Both safeguard transitions and cancelled contracts are independent properties of the SAME project list — fan-out, NOT a chain.
{"picks": [
   {"id": "p0", "gateway_id": "gw_projects",
    "sub_question": "List ONLY the project_id for FCV-country projects approved in FY2022 — return just project_id, no other columns.",
    "depends_on": [], "bind": []},
   {"id": "p1", "gateway_id": "gw_safeguards",
    "sub_question": "Safeguard category transition dates for projects {{project_ids}}.",
    "depends_on": ["p0"],
    "bind": [{"placeholder": "project_ids", "upstream": "p0", "column": "project_id", "reducer": "list"}]},
   {"id": "p2", "gateway_id": "gw_procurement",
    "sub_question": "Cancelled contract amounts per project for projects {{project_ids}}.",
    "depends_on": ["p0"],
    "bind": [{"placeholder": "project_ids", "upstream": "p0", "column": "project_id", "reducer": "list"}]}
 ],
 "decomposed": true,
 "rationale": "Fan-out: safeguards and procurement are independent properties of the same project list."}"""


@dataclass
class RoomPick:
    gateway_id: str
    sub_question: str
    id: str = ""  # stable id within a decision (e.g. "p0"); auto-synthesized if empty
    depends_on: list = field(default_factory=list)
    bind: list = field(default_factory=list)

    def model_dump(self) -> dict:
        return {
            "id": self.id,
            "gateway_id": self.gateway_id,
            "sub_question": self.sub_question,
            "depends_on": list(self.depends_on),
            "bind": [dict(b) for b in self.bind],
        }


@dataclass
class RoutingDecision:
    picks: list = field(default_factory=list)
    decomposed: bool = False
    rationale: str = ""

    def model_dump(self) -> dict:
        return {
            "picks": [p.model_dump() if isinstance(p, RoomPick) else p for p in self.picks],
            "decomposed": self.decomposed,
            "rationale": self.rationale,
        }


def _catalog_as_prompt(members: list[dict]) -> str:
    lines = []
    for m in members:
        if m.get("disabled"):
            continue
        lines.append(f"## gateway_id: {m['gateway_id']}")
        lines.append(f"title: {m.get('title') or m['gateway_id']}")
        lines.append(f"when_to_use: {(m.get('when_to_use') or '').strip()}")
        tables = m.get("tables") or []
        if tables:
            lines.append(f"tables: {', '.join(tables)}")
        samples = m.get("sample_questions") or []
        if samples:
            lines.append("sample_questions:")
            for q in samples:
                lines.append(f"  - {q}")
        lines.append("")
    return "\n".join(lines).strip()


def _extract_content(data: Any) -> str:
    choices = (data or {}).get("choices") or []
    if choices:
        msg = choices[0].get("message") or {}
        return msg.get("content") or ""
    preds = (data or {}).get("predictions") or []
    if preds:
        return str(preds[0])
    return ""


def _is_claude_endpoint(endpoint: str) -> bool:
    """Endpoints whose serving stack rejects `response_format: json_object`.

    Databricks FMAPI is OpenAI-compatible but the per-model wrappers around
    Bedrock-served Claude reject `response_format` (verified on FEVM
    2026-04-27 with `databricks-claude-haiku-4-5`). Llama-served-on-DBX
    accepts it. We branch on endpoint name rather than detect at runtime to
    keep the request shape stable per model.
    """
    return "claude" in (endpoint or "").lower()


def _build_selector_body(endpoint: str, system_prompt: str, user_prompt: str) -> dict:
    r"""Construct the FMAPI invocation body, with per-endpoint shape adjustments.

    Llama-4-maverick accepts the full OpenAI shape including
    `response_format: {type: json_object}`. Claude on Databricks (Bedrock-
    proxied) rejects that field — we drop it and rely on the prompt
    instruction to constrain the output to JSON. The fence-tolerant parser
    `_parse_json_content` handles Claude's occasional ```json ... ```
    wrapping at the read side.
    """
    body: dict = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        # DAG schema has more tokens per pick (id/depends_on/bind); give it room
        # for 3-stage plans with bind entries without truncating.
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
    }
    if _is_claude_endpoint(endpoint):
        body.pop("response_format", None)
    return body
    # Note: tried `seed: 42` for FMAPI determinism on 2026-04-27 — Llama
    # rejects it with BadRequest (strict schema validation). Not all
    # OpenAI-compatible servers accept `seed`. See project_selector_temp_finding.


def _parse_json_content(content: str) -> dict:
    """Parse JSON from a chat-completion content string, tolerating fences.

    Tries `json.loads` first (Llama path: clean JSON when response_format is
    set). On JSONDecodeError, strips a single leading code fence (with or
    without a `json` language tag) plus its closing ``` and retries
    (Claude path: the model occasionally wraps complex outputs even when
    asked not to). Raises ValueError if neither attempt parses.
    """
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    s = (content or "").strip()
    # Find a fenced block: ```json ... ``` OR ``` ... ```
    if s.startswith("```"):
        # drop the opening fence line
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]
        else:
            s = s[3:]
        # drop trailing ``` if present (with or without trailing text)
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        elif "```" in s:
            s = s.rsplit("```", 1)[0]
    try:
        return json.loads(s.strip())
    except json.JSONDecodeError as e:
        raise ValueError(f"content is not parseable JSON (with or without fence): {e}") from e


def _active_members(members: list[dict]) -> list[dict]:
    return [m for m in members if not m.get("disabled")]


async def select_rooms(
    question: str,
    members: list[dict],
    *,
    token: str,
    databricks_host: str,
    model: str | None = None,
    system_prompt: str | None = None,
    hints: list[str] | None = None,
) -> RoutingDecision:
    """Call the selector LLM and return a RoutingDecision.

    Fails open: on LLM error or unparseable response, returns a decision that
    picks the first active member with a diagnostic rationale. This keeps
    routing live during incidents while emitting enough signal to investigate.
    """
    active = _active_members(members)
    if not active:
        return RoutingDecision(picks=[], decomposed=False, rationale="no active members in router")

    # Single-member shortcut — skip the LLM.
    if len(active) == 1:
        only = active[0]
        return RoutingDecision(
            picks=[RoomPick(id="p0", gateway_id=only["gateway_id"], sub_question=question)],
            decomposed=False,
            rationale=f"only one active member ({only['gateway_id']})",
        )

    endpoint = model or SELECTOR_DEFAULT_ENDPOINT
    prompt = system_prompt or _SYSTEM_PROMPT_DEFAULT

    user_prompt = f"Catalog:\n{_catalog_as_prompt(active)}\n\nQuestion: {question}"
    if hints:
        user_prompt += f"\n\nHints from caller: {'; '.join(hints)}"
    # FMAPI's response_format check wants the literal lowercase word "json" in
    # the user message (not just the system prompt), so we append an explicit
    # instruction here too.
    user_prompt += "\n\nRespond with a json object only."

    body = _build_selector_body(endpoint, prompt, user_prompt)

    if not token:
        logger.warning("Selector: no user token — falling back to first active member")
        fallback = active[0]
        return RoutingDecision(
            picks=[RoomPick(id="p0", gateway_id=fallback["gateway_id"], sub_question=question)],
            decomposed=False,
            rationale="selector skipped: no user token; fell back to first active member",
        )

    try:
        config = Config(host=databricks_host, token=token, auth_type="pat")
        client = WorkspaceClient(config=config)
        response = client.api_client.do(
            "POST",
            f"/serving-endpoints/{endpoint}/invocations",
            body=body,
        )
    except Exception as e:
        logger.warning("Selector LLM call failed (endpoint=%s): %s — falling back to first active member", endpoint, e)
        fallback = active[0]
        return RoutingDecision(
            picks=[RoomPick(id="p0", gateway_id=fallback["gateway_id"], sub_question=question)],
            decomposed=False,
            rationale=f"selector failed ({type(e).__name__}); fell back to {fallback['gateway_id']}",
        )

    content = _extract_content(response)
    try:
        parsed = _parse_json_content(content)
    except (ValueError, json.JSONDecodeError):
        logger.warning("Selector returned non-JSON (endpoint=%s): %s", endpoint, content[:200])
        return RoutingDecision(picks=[], decomposed=False, rationale="selector returned non-JSON")

    picks = _parse_picks(parsed.get("picks") or [], active)

    return RoutingDecision(
        picks=picks,
        decomposed=bool(parsed.get("decomposed", len(picks) > 1)),
        rationale=str(parsed.get("rationale", ""))[:200],
    )


# ---------------------------------------------------------------------------
# Pick validation / normalization
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_ALLOWED_REDUCERS = {"list", "scalar", "first_n"}


def _parse_picks(raw_picks: list, active_members: list[dict]) -> list[RoomPick]:
    """Normalize selector output into validated RoomPick objects.

    Responsibilities:
    - Drop picks with unknown gateway_id or missing sub_question.
    - Synthesize `id` as `p{idx}` when missing; deduplicate colliding ids.
    - Validate `depends_on` entries point to earlier picks (forward-only).
    - Validate `bind` entries: shape, upstream in depends_on, known reducer.
    - Validate that every bind.placeholder appears as `{{placeholder}}` in
      sub_question AND that every `{{placeholder}}` in sub_question has a bind.
    - On validation failure for a pick, strip depends_on+bind and keep the
      raw sub_question — better to run the pick unbound than drop it silently.
    """
    valid_ids = {m["gateway_id"] for m in active_members}
    result: list[RoomPick] = []
    used_ids: set[str] = set()

    for idx, p in enumerate(raw_picks):
        if not isinstance(p, dict):
            continue
        gw = p.get("gateway_id")
        sub_q = p.get("sub_question")
        if gw not in valid_ids or not sub_q or not isinstance(sub_q, str):
            continue

        # Synthesize or dedupe id.
        pid = p.get("id") or f"p{idx}"
        if not isinstance(pid, str) or not pid:
            pid = f"p{idx}"
        if pid in used_ids:
            # Collision — append a suffix to keep ids unique.
            base = pid
            n = 1
            while f"{base}_{n}" in used_ids:
                n += 1
            pid = f"{base}_{n}"
        used_ids.add(pid)

        earlier_ids = {r.id for r in result}
        depends_on_raw = p.get("depends_on") or []
        if not isinstance(depends_on_raw, list):
            depends_on_raw = []
        depends_on = [d for d in depends_on_raw if isinstance(d, str) and d in earlier_ids]
        # If the model listed unknown upstreams, warn and drop just those refs.
        if len(depends_on) != len([d for d in depends_on_raw if isinstance(d, str)]):
            logger.warning(
                "Selector pick %s had unknown depends_on entries (kept %s of %s)",
                pid, depends_on, depends_on_raw,
            )

        bind_raw = p.get("bind") or []
        if not isinstance(bind_raw, list):
            bind_raw = []
        bind: list[dict] = []
        for b in bind_raw:
            if not isinstance(b, dict):
                continue
            placeholder = b.get("placeholder")
            upstream = b.get("upstream")
            column = b.get("column")
            reducer = b.get("reducer") or "list"
            if not (isinstance(placeholder, str) and placeholder
                    and isinstance(upstream, str) and upstream in depends_on
                    and isinstance(column, str) and column
                    and reducer in _ALLOWED_REDUCERS):
                continue
            bind.append({
                "placeholder": placeholder,
                "upstream": upstream,
                "column": column,
                "reducer": reducer,
            })

        # Cross-check placeholders ↔ bind entries.
        placeholders_in_text = set(_PLACEHOLDER_RE.findall(sub_q))
        bind_names = {b["placeholder"] for b in bind}
        if placeholders_in_text != bind_names or (placeholders_in_text and not depends_on):
            logger.warning(
                "Selector pick %s placeholder/bind mismatch (text=%s, bind=%s, depends_on=%s) — stripping deps",
                pid, placeholders_in_text, bind_names, depends_on,
            )
            depends_on = []
            bind = []

        result.append(RoomPick(
            id=pid,
            gateway_id=gw,
            sub_question=sub_q,
            depends_on=depends_on,
            bind=bind,
        ))

    return result
