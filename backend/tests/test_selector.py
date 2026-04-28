"""Tests for selector body shaping + JSON content parsing.

Covers the per-model body adapter (Llama keeps `response_format`, Claude
strips it because Bedrock-proxied endpoints reject it) and the
fence-tolerant JSON parser added to handle Claude's occasional markdown
fence wrapping. See plan: selector swap to Claude Haiku, 2026-04-27.

The selector module imports `databricks.sdk.core.Config` and
`databricks.sdk.WorkspaceClient` at top level — stub them before importing
the unit under test.
"""
import json
import sys
import types
from unittest.mock import MagicMock

import pytest

# Stub databricks.sdk.core before selector imports
if "databricks.sdk.core" not in sys.modules:
    core_stub = types.ModuleType("databricks.sdk.core")
    core_stub.Config = MagicMock()
    sys.modules["databricks.sdk.core"] = core_stub
    if "databricks.sdk" in sys.modules:
        sys.modules["databricks.sdk"].core = core_stub

from app.services.selector import (  # noqa: E402
    _build_selector_body,
    _is_claude_endpoint,
    _parse_json_content,
)


# ---- _is_claude_endpoint --------------------------------------------------


def test_is_claude_endpoint_matches_claude_models():
    assert _is_claude_endpoint("databricks-claude-haiku-4-5")
    assert _is_claude_endpoint("databricks-claude-opus-4-6")
    assert _is_claude_endpoint("CLAUDE-3-5-SONNET")  # case-insensitive


def test_is_claude_endpoint_does_not_match_llama():
    assert not _is_claude_endpoint("databricks-llama-4-maverick")
    assert not _is_claude_endpoint("databricks-meta-llama-3-70b")
    assert not _is_claude_endpoint("")
    assert not _is_claude_endpoint(None)


# ---- _build_selector_body -------------------------------------------------


def test_body_includes_response_format_for_llama():
    body = _build_selector_body("databricks-llama-4-maverick", "system", "user")
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 1024
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"


def test_body_strips_response_format_for_claude():
    """Bedrock-proxied Claude rejects response_format with INVALID_PARAMETER_VALUE.
    Verified on FEVM 2026-04-27. Llama-only param must be conditional."""
    body = _build_selector_body("databricks-claude-haiku-4-5", "system", "user")
    assert "response_format" not in body
    # Other params still present
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 1024
    assert body["messages"][0]["content"] == "system"
    assert body["messages"][1]["content"] == "user"


def test_body_default_endpoint_keeps_response_format():
    """Defensive: empty endpoint string falls through to Llama-shape body."""
    body = _build_selector_body("", "s", "u")
    assert body["response_format"] == {"type": "json_object"}


# ---- _parse_json_content --------------------------------------------------


def test_parse_json_content_raw_json():
    content = '{"picks": [{"id": "p0", "gateway_id": "abc"}], "decomposed": false}'
    out = _parse_json_content(content)
    assert out["decomposed"] is False
    assert out["picks"][0]["id"] == "p0"


def test_parse_json_content_strips_json_fence():
    content = '```json\n{"picks": [], "decomposed": false}\n```'
    out = _parse_json_content(content)
    assert out == {"picks": [], "decomposed": False}


def test_parse_json_content_strips_plain_fence():
    content = '```\n{"picks": [], "rationale": "x"}\n```'
    out = _parse_json_content(content)
    assert out["rationale"] == "x"


def test_parse_json_content_handles_trailing_text_after_fence():
    """Some models close the fence then add a sentence — strip it."""
    content = '```json\n{"a": 1}\n```\n\nLet me know if you have questions.'
    out = _parse_json_content(content)
    assert out == {"a": 1}


def test_parse_json_content_raises_on_garbage():
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _parse_json_content("this is plainly not JSON at all")


def test_parse_json_content_handles_empty_string():
    """Empty content should raise, not silently return None."""
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _parse_json_content("")
