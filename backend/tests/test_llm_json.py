"""Tests for the shared FMAPI JSON-mode helpers.

Covers:
- Static endpoint family detection (Claude vs Llama vs unknown).
- `build_json_body` shape — strips response_format for Claude AND for any
  endpoint cached as denied at runtime.
- `parse_json_content` fence-tolerance.
- `invoke_json` runtime fallback: on a `response_format` error, retries
  without it AND caches the endpoint in the deny set. Unrelated errors
  propagate without poisoning the deny cache.
"""

import json
from unittest.mock import MagicMock

import pytest

from app.services import llm_json
from app.services.llm_json import (
    JSON_INSTRUCTION,
    build_json_body,
    invoke_json,
    is_claude_endpoint,
    parse_json_content,
)


@pytest.fixture(autouse=True)
def _clear_deny_cache():
    """Reset the deny cache between tests so they don't leak state."""
    llm_json._DENY_RESPONSE_FORMAT.clear()
    yield
    llm_json._DENY_RESPONSE_FORMAT.clear()


# ---- is_claude_endpoint ---------------------------------------------------


def test_is_claude_endpoint_matches_claude_models():
    assert is_claude_endpoint("databricks-claude-haiku-4-5")
    assert is_claude_endpoint("databricks-claude-opus-4-6")
    assert is_claude_endpoint("CLAUDE-3-5-SONNET")  # case-insensitive


def test_is_claude_endpoint_does_not_match_other_families():
    assert not is_claude_endpoint("databricks-llama-4-maverick")
    assert not is_claude_endpoint("databricks-meta-llama-3-70b")
    assert not is_claude_endpoint("databricks-gpt-oss-120b")
    assert not is_claude_endpoint("databricks-gemma-3-12b")
    assert not is_claude_endpoint("databricks-gemini-2-5-pro")
    assert not is_claude_endpoint("")
    assert not is_claude_endpoint(None)


# ---- build_json_body ------------------------------------------------------


def test_build_body_keeps_response_format_for_llama():
    body = build_json_body("databricks-llama-4-maverick", [{"role": "user", "content": "hi"}])
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["temperature"] == 0.0


def test_build_body_strips_response_format_for_claude():
    body = build_json_body("databricks-claude-haiku-4-5", [{"role": "user", "content": "hi"}])
    assert "response_format" not in body
    assert body["messages"] == [{"role": "user", "content": "hi"}]


def test_build_body_strips_response_format_for_denied_endpoint():
    """Once an endpoint is added to the runtime deny cache, body builder skips it."""
    llm_json._DENY_RESPONSE_FORMAT.add("databricks-mystery-model")
    body = build_json_body("databricks-mystery-model", [{"role": "user", "content": "hi"}])
    assert "response_format" not in body


def test_build_body_includes_max_tokens_when_set():
    body = build_json_body("databricks-llama-4-maverick", [], max_tokens=512)
    assert body["max_tokens"] == 512


def test_build_body_omits_max_tokens_when_none():
    body = build_json_body("databricks-llama-4-maverick", [])
    assert "max_tokens" not in body


def test_build_body_uses_provided_temperature():
    body = build_json_body("databricks-llama-4-maverick", [], temperature=0.7)
    assert body["temperature"] == 0.7


# ---- parse_json_content ---------------------------------------------------


def test_parse_clean_json():
    assert parse_json_content('{"a": 1}') == {"a": 1}


def test_parse_strips_json_fence():
    assert parse_json_content('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_strips_plain_fence():
    assert parse_json_content('```\n{"a": 1}\n```') == {"a": 1}


def test_parse_handles_trailing_text_after_fence():
    content = '```json\n{"a": 1}\n```\n\nLet me know if you have questions.'
    assert parse_json_content(content) == {"a": 1}


def test_parse_raises_on_garbage():
    with pytest.raises(ValueError):
        parse_json_content("this is plainly not JSON")


def test_parse_raises_on_empty_string():
    with pytest.raises((ValueError, json.JSONDecodeError)):
        parse_json_content("")


# ---- invoke_json ----------------------------------------------------------


def _make_client(responses):
    """Build a mock WorkspaceClient.

    `responses` is a list of values returned in order. Exception instances in
    the list are raised when their slot is reached (this is a built-in
    feature of unittest.mock when `side_effect` is an iterable).
    """
    client = MagicMock()
    client.api_client.do.side_effect = list(responses)
    return client


def _ok_response(content):
    return {"choices": [{"message": {"content": content}}]}


def test_invoke_json_happy_path_llama():
    client = _make_client([_ok_response('{"hello": "world"}')])
    result = invoke_json(client, "databricks-llama-4-maverick", [{"role": "user", "content": "hi"}])
    assert result == {"hello": "world"}
    # Confirm the body included response_format
    call_args = client.api_client.do.call_args_list[0]
    body = call_args.kwargs["body"]
    assert body["response_format"] == {"type": "json_object"}


def test_invoke_json_happy_path_claude_strips_response_format():
    client = _make_client([_ok_response('{"x": 1}')])
    result = invoke_json(client, "databricks-claude-haiku-4-5", [{"role": "user", "content": "hi"}])
    assert result == {"x": 1}
    body = client.api_client.do.call_args_list[0].kwargs["body"]
    assert "response_format" not in body


def test_invoke_json_retries_on_response_format_error():
    """First call rejects response_format → cache + retry without it → 200."""
    err = Exception("INVALID_PARAMETER_VALUE: Response format type json_object is not supported for this model.")
    client = _make_client([err, _ok_response('{"ok": true}')])

    result = invoke_json(client, "databricks-mystery-model", [{"role": "user", "content": "hi"}])

    assert result == {"ok": True}
    assert "databricks-mystery-model" in llm_json._DENY_RESPONSE_FORMAT
    # First call had response_format, second did not
    first_body = client.api_client.do.call_args_list[0].kwargs["body"]
    second_body = client.api_client.do.call_args_list[1].kwargs["body"]
    assert first_body["response_format"] == {"type": "json_object"}
    assert "response_format" not in second_body


def test_invoke_json_does_not_cache_unrelated_errors():
    """Errors that don't mention response_format must propagate without poisoning the cache."""
    err = Exception("403 Forbidden: insufficient permissions")
    client = _make_client([err])

    with pytest.raises(Exception, match="Forbidden"):
        invoke_json(client, "databricks-some-model", [{"role": "user", "content": "hi"}])

    assert "databricks-some-model" not in llm_json._DENY_RESPONSE_FORMAT


def test_invoke_json_does_not_retry_for_claude_endpoint():
    """Claude endpoints already strip response_format pre-call. If they still
    raise a response_format error, that's unexpected — propagate, don't retry."""
    err = Exception("response_format is unexpectedly bad")
    client = _make_client([err])

    with pytest.raises(Exception):
        invoke_json(client, "databricks-claude-haiku-4-5", [{"role": "user", "content": "hi"}])

    # Claude was never expected to support it, so deny-cache shouldn't change behavior.
    # Crucially, only one call was made (no retry).
    assert client.api_client.do.call_count == 1


def test_invoke_json_subsequent_call_to_denied_endpoint_skips_response_format():
    """After the first call cached the endpoint, the second call shouldn't even try response_format."""
    err = Exception("INVALID_PARAMETER_VALUE: response_format")
    client = _make_client([err, _ok_response('{"a": 1}'), _ok_response('{"b": 2}')])

    invoke_json(client, "databricks-foo", [{"role": "user", "content": "hi"}])
    invoke_json(client, "databricks-foo", [{"role": "user", "content": "hi"}])

    # Total of 3 do() calls: first attempt (with rf), retry (without), second invoke (without).
    assert client.api_client.do.call_count == 3
    third_body = client.api_client.do.call_args_list[2].kwargs["body"]
    assert "response_format" not in third_body


def test_invoke_json_propagates_parse_failure():
    """If the response content isn't JSON-parseable, raise ValueError."""
    client = _make_client([_ok_response("this is not json at all")])

    with pytest.raises(ValueError):
        invoke_json(client, "databricks-llama-4-maverick", [{"role": "user", "content": "hi"}])


# ---- JSON_INSTRUCTION -----------------------------------------------------


def test_json_instruction_contains_lowercase_json():
    """FMAPI's response_format check requires the literal lowercase word 'json'
    in the user message. The constant must satisfy this."""
    assert "json" in JSON_INSTRUCTION
