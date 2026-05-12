"""Unit tests for the cache validator response parser.

Mirrors the test shape of test_intent_splitter.py. The parser now goes
through `parse_json_content`, so it tolerates ```json fences (Claude
sometimes wraps even when asked not to).
"""

from app.services.cache_validator import _extract_is_cache_valid, _parse_is_cache_valid


def test_parse_clean_true():
    assert _parse_is_cache_valid('{"is_cache_valid": true}') is True


def test_parse_clean_false():
    assert _parse_is_cache_valid('{"is_cache_valid": false}') is False


def test_parse_string_true():
    assert _parse_is_cache_valid('{"is_cache_valid": "true"}') is True
    assert _parse_is_cache_valid('{"is_cache_valid": "TRUE"}') is True
    assert _parse_is_cache_valid('{"is_cache_valid": "yes"}') is True
    assert _parse_is_cache_valid('{"is_cache_valid": "1"}') is True


def test_parse_string_false():
    assert _parse_is_cache_valid('{"is_cache_valid": "false"}') is False
    assert _parse_is_cache_valid('{"is_cache_valid": "FALSE"}') is False
    assert _parse_is_cache_valid('{"is_cache_valid": "no"}') is False
    assert _parse_is_cache_valid('{"is_cache_valid": "0"}') is False


def test_parse_string_unrecognized_returns_none():
    assert _parse_is_cache_valid('{"is_cache_valid": "maybe"}') is None
    assert _parse_is_cache_valid('{"is_cache_valid": ""}') is None


def test_parse_numeric_value():
    assert _parse_is_cache_valid('{"is_cache_valid": 1}') is True
    assert _parse_is_cache_valid('{"is_cache_valid": 0}') is False


def test_parse_invalid_json_returns_none():
    assert _parse_is_cache_valid("not json at all") is None


def test_parse_markdown_fenced_parses_correctly():
    # Claude sometimes wraps in ```json fences; parse_json_content strips them.
    assert _parse_is_cache_valid('```json\n{"is_cache_valid": true}\n```') is True
    assert _parse_is_cache_valid('```\n{"is_cache_valid": false}\n```') is False


def test_parse_missing_key_returns_none():
    assert _parse_is_cache_valid('{"other_field": true}') is None
    assert _parse_is_cache_valid("{}") is None


def test_parse_null_value_returns_none():
    assert _parse_is_cache_valid('{"is_cache_valid": null}') is None


def test_parse_non_object_json_returns_none():
    assert _parse_is_cache_valid("true") is None
    assert _parse_is_cache_valid("[true]") is None
    assert _parse_is_cache_valid('"a string"') is None


def test_parse_non_string_input_returns_none():
    assert _parse_is_cache_valid(None) is None  # type: ignore[arg-type]
    assert _parse_is_cache_valid(123) is None  # type: ignore[arg-type]


def test_parse_array_value_returns_none():
    assert _parse_is_cache_valid('{"is_cache_valid": [true]}') is None


# ---- _extract_is_cache_valid (dict input from invoke_json) ----------------


def test_extract_clean_bool():
    assert _extract_is_cache_valid({"is_cache_valid": True}) is True
    assert _extract_is_cache_valid({"is_cache_valid": False}) is False


def test_extract_string_coercion():
    assert _extract_is_cache_valid({"is_cache_valid": "yes"}) is True
    assert _extract_is_cache_valid({"is_cache_valid": "no"}) is False


def test_extract_missing_key_returns_none():
    assert _extract_is_cache_valid({}) is None
    assert _extract_is_cache_valid({"other": True}) is None


def test_extract_non_dict_returns_none():
    assert _extract_is_cache_valid(None) is None
    assert _extract_is_cache_valid([{"is_cache_valid": True}]) is None
    assert _extract_is_cache_valid("string") is None
