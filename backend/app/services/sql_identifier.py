"""Postgres SQL identifier quoting.

asyncpg has no public equivalent of psycopg's `sql.Identifier()`. This helper
implements the same rules as `pg_catalog.quote_ident()`: wrap the identifier
in double-quotes, escape any internal double-quotes by doubling them.

We always quote (rather than only-quote-when-needed) because the cost is one
extra character on a string that's about to round-trip Postgres, and the rules
for "needs quoting" are subtle (reserved words, leading digits, mixed case).

For multi-part identifiers like `schema.table`, use `quote_qualified()`.
"""

from __future__ import annotations


def quote_ident(name: str) -> str:
    """Quote a Postgres identifier per `pg_catalog.quote_ident()` semantics."""
    if not isinstance(name, str):
        raise TypeError(f"quote_ident expects str, got {type(name).__name__}")
    if "\x00" in name:
        raise ValueError("Postgres identifiers cannot contain NULL bytes")
    return '"' + name.replace('"', '""') + '"'


def quote_qualified(qualified_name: str) -> str:
    """Quote each part of a dotted identifier (`schema.table` → `"schema"."table"`)."""
    return ".".join(quote_ident(part) for part in qualified_name.split("."))
