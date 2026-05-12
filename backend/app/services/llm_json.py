"""Shared helpers for FMAPI JSON-mode chat completions across model families.

Databricks FMAPI is OpenAI-compatible but not all model wrappers accept the
OpenAI-style `response_format: {type: json_object}` field. Bedrock-served
Claude rejects it with `INVALID_PARAMETER_VALUE` (verified on FEVM
2026-04-27 with `databricks-claude-haiku-4-5`); Llama-served-on-DBX accepts
it. Behavior of newer or open-source endpoints (Gemini, GPT-OSS, Gemma) is
not centrally documented, so this module combines:

- Static name-based detection for known-rejecting families (Claude today).
- A per-process deny-cache (`_DENY_RESPONSE_FORMAT`) populated by runtime
  retries — the first call to a previously-unknown rejecting endpoint pays
  one round-trip + one retry, every subsequent call skips response_format
  outright.

All three optional LLM passes (cache_validator, intent_splitter, selector)
go through `invoke_json`. The fence-tolerant `parse_json_content` handles
markdown-wrapped JSON that some models emit even when asked not to.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# Appended to user prompts so FMAPI's `response_format` validator finds the
# literal lowercase word "json" in the message — required when
# `response_format: json_object` is set, harmless otherwise.
JSON_INSTRUCTION = "Respond with a json object only."


# Endpoints observed at runtime to reject `response_format`. Process-lifetime
# only — no persistence, no locking. Set add is idempotent under concurrency.
_DENY_RESPONSE_FORMAT: set[str] = set()


def is_claude_endpoint(name: str | None) -> bool:
    """Endpoints whose serving stack rejects `response_format: json_object`.

    Claude on Databricks (Bedrock-proxied) rejects `response_format`
    (verified on FEVM 2026-04-27 with `databricks-claude-haiku-4-5`).
    Match by substring so naming variations like
    `databricks-claude-3-5-sonnet`, `CLAUDE-haiku-4-5`, etc. are caught.
    """
    return "claude" in (name or "").lower()


def build_json_body(
    endpoint: str,
    messages: list[dict],
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> dict:
    """Construct the FMAPI invocation body, with per-endpoint shape adjustments.

    Adds `response_format: {type: json_object}` unless the endpoint is in a
    known-rejecting family (Claude) or has been observed to reject it at
    runtime (`_DENY_RESPONSE_FORMAT`).
    """
    body: dict[str, Any] = {
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if not is_claude_endpoint(endpoint) and endpoint not in _DENY_RESPONSE_FORMAT:
        body["response_format"] = {"type": "json_object"}
    return body


def parse_json_content(content: str) -> dict:
    """Parse JSON from a chat-completion content string, tolerating fences.

    Tries `json.loads` first (clean JSON when response_format is set). On
    JSONDecodeError, strips a single leading code fence (with or without a
    `json` language tag) plus its closing ``` and retries (Claude path: the
    model occasionally wraps complex outputs even when asked not to).
    Raises ValueError if neither attempt parses.
    """
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    s = (content or "").strip()
    if s.startswith("```"):
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]
        else:
            s = s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        elif "```" in s:
            s = s.rsplit("```", 1)[0]
    try:
        return json.loads(s.strip())
    except json.JSONDecodeError as e:
        raise ValueError(f"content is not parseable JSON (with or without fence): {e}") from e


def _is_response_format_error(exc: Exception) -> bool:
    """Heuristic: did the FMAPI failure complain about `response_format`?

    Match loosely. Databricks' error wording ("Response format type
    json_object is not supported for this model.") uses a space; the OpenAI
    parameter name uses an underscore; either could appear depending on
    where the error originated. We accept both, plus a fallback on the
    `json_object` literal.
    """
    s = str(exc).lower()
    return (
        "response_format" in s
        or "response format" in s
        or "json_object" in s
    )


def invoke_json(
    client,
    endpoint: str,
    messages: list[dict],
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> dict:
    """Call FMAPI chat-completions and return the parsed JSON content.

    On the first call to an unknown rejecting endpoint, FMAPI returns
    `INVALID_PARAMETER_VALUE: Response format type json_object is not
    supported for this model.` We catch that, add the endpoint to the
    deny cache, and retry once without `response_format`. Subsequent calls
    skip `response_format` for that endpoint outright.

    Errors unrelated to `response_format` propagate to the caller.
    """
    body = build_json_body(
        endpoint, messages, temperature=temperature, max_tokens=max_tokens
    )
    path = f"/serving-endpoints/{endpoint}/invocations"
    try:
        response = client.api_client.do("POST", path, body=body)
    except Exception as e:
        if "response_format" not in body or not _is_response_format_error(e):
            raise
        logger.info(
            "FMAPI endpoint %s rejected response_format; caching deny + retrying without it",
            endpoint,
        )
        _DENY_RESPONSE_FORMAT.add(endpoint)
        retry_body = {k: v for k, v in body.items() if k != "response_format"}
        response = client.api_client.do("POST", path, body=retry_body)

    content = response["choices"][0]["message"]["content"]
    return parse_json_content(content)
