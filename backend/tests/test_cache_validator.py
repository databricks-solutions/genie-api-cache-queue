"""Unit tests for the cache validator response parser.

Mirrors the test shape of test_intent_splitter.py — native JSON mode means we
never need to fence-strip, so any parse failure should return None and the
caller fails open.
"""

from app.services.cache_validator import _parse_is_cache_valid


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


def test_parse_markdown_fenced_returns_none():
    # Native JSON mode should never produce fences; if it does, fail open.
    assert _parse_is_cache_valid('```json\n{"is_cache_valid": true}\n```') is None


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
