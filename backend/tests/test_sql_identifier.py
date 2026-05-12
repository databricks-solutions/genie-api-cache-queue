import pytest

from app.services.sql_identifier import quote_ident, quote_qualified


def test_simple_identifier():
    assert quote_ident("users") == '"users"'


def test_uppercase_preserved():
    assert quote_ident("Users") == '"Users"'


def test_mixed_case_with_digits():
    assert quote_ident("user_123") == '"user_123"'


def test_leading_digit():
    assert quote_ident("1table") == '"1table"'


def test_internal_quote_escaped():
    assert quote_ident('weird"name') == '"weird""name"'


def test_multiple_internal_quotes():
    assert quote_ident('"a"b"c"') == '"""a""b""c"""'


def test_reserved_word():
    assert quote_ident("select") == '"select"'


def test_empty_string():
    assert quote_ident("") == '""'


def test_unicode_name():
    assert quote_ident("café_logs") == '"café_logs"'


def test_null_byte_rejected():
    with pytest.raises(ValueError):
        quote_ident("bad\x00name")


def test_non_string_rejected():
    with pytest.raises(TypeError):
        quote_ident(None)
    with pytest.raises(TypeError):
        quote_ident(123)


def test_qualified_two_parts():
    assert quote_qualified("genie_cache.cached_queries") == '"genie_cache"."cached_queries"'


def test_qualified_three_parts():
    assert quote_qualified("catalog.schema.table") == '"catalog"."schema"."table"'


def test_qualified_with_quotes():
    assert quote_qualified('weird".sch') == '"weird"""."sch"'


def test_qualified_single_part():
    assert quote_qualified("public") == '"public"'
