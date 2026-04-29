"""Unit tests for the intent splitter response parser.

The parser now goes through `parse_json_content`, so it tolerates ```json
fences (Claude sometimes wraps even when asked not to).
"""

from app.services.intent_splitter import _extract_latest_intent, _parse_latest_intent


def test_parse_clean_json():
    assert _parse_latest_intent('{"latest_intent": "show me sales last week"}') == "show me sales last week"


def test_parse_strips_whitespace():
    assert _parse_latest_intent('{"latest_intent": "  hello  "}') == "hello"


def test_parse_invalid_json_returns_none():
    assert _parse_latest_intent("not json at all") is None


def test_parse_markdown_fenced_parses_correctly():
    # Claude sometimes wraps in ```json fences; parse_json_content strips them.
    assert _parse_latest_intent('```json\n{"latest_intent": "x"}\n```') == "x"
    assert _parse_latest_intent('```\n{"latest_intent": "y"}\n```') == "y"


def test_parse_missing_key_returns_none():
    assert _parse_latest_intent('{"other_field": "x"}') is None


def test_parse_non_string_value_returns_none():
    assert _parse_latest_intent('{"latest_intent": 123}') is None
    assert _parse_latest_intent('{"latest_intent": null}') is None
    assert _parse_latest_intent('{"latest_intent": ["a"]}') is None


def test_parse_empty_string_value_returns_none():
    assert _parse_latest_intent('{"latest_intent": ""}') is None
    assert _parse_latest_intent('{"latest_intent": "   "}') is None


def test_parse_non_object_json_returns_none():
    assert _parse_latest_intent('"just a string"') is None
    assert _parse_latest_intent("[1, 2, 3]") is None


def test_parse_non_string_input_returns_none():
    assert _parse_latest_intent(None) is None  # type: ignore[arg-type]
    assert _parse_latest_intent(123) is None  # type: ignore[arg-type]


def test_parse_preserves_multiline_content():
    payload = '{"latest_intent": "line one\\nline two\\nline three"}'
    assert _parse_latest_intent(payload) == "line one\nline two\nline three"


# ---- _extract_latest_intent (dict input from invoke_json) -----------------


def test_extract_clean_string():
    assert _extract_latest_intent({"latest_intent": "show sales"}) == "show sales"


def test_extract_strips_whitespace():
    assert _extract_latest_intent({"latest_intent": "  hello  "}) == "hello"


def test_extract_missing_key_returns_none():
    assert _extract_latest_intent({}) is None
    assert _extract_latest_intent({"other": "x"}) is None


def test_extract_non_string_value_returns_none():
    assert _extract_latest_intent({"latest_intent": 123}) is None
    assert _extract_latest_intent({"latest_intent": None}) is None


def test_extract_empty_string_returns_none():
    assert _extract_latest_intent({"latest_intent": ""}) is None
    assert _extract_latest_intent({"latest_intent": "   "}) is None


def test_extract_non_dict_returns_none():
    assert _extract_latest_intent(None) is None
    assert _extract_latest_intent([{"latest_intent": "x"}]) is None
    assert _extract_latest_intent("string") is None
