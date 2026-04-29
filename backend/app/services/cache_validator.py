"""
LLM-based cache validation service.

Validates that a cached query is semantically equivalent to the incoming query
to avoid false cache hits from vector similarity alone (e.g. "Revenue in Q1"
vs "Revenue in Q2"). Uses native JSON mode where the model supports it and
falls back to fence-tolerant parsing for models that don't (Claude wraps
output in ```json fences even when asked not to).
"""

import logging

from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

from app.config import get_settings
from app.services import tracing
from app.services.llm_json import JSON_INSTRUCTION, invoke_json, parse_json_content

logger = logging.getLogger(__name__)
settings = get_settings()

# Default Databricks Foundation Model endpoint used for validation.
# Can be overridden per-gateway or globally via RuntimeSettings.validation_model.
CACHE_VALIDATION_LLM_ENDPOINT = "databricks-llama-4-maverick"


def _extract_is_cache_valid(parsed) -> bool | None:
    """Coerce the `is_cache_valid` field from an already-parsed dict.

    Returns True/False on a valid value, or None on missing/non-coercible
    value. The caller treats None as fail-open (= valid hit).
    """
    if not isinstance(parsed, dict):
        return None

    value = parsed.get("is_cache_valid")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "yes", "1"):
            return True
        if v in ("false", "no", "0"):
            return False
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    return None


def _parse_is_cache_valid(content: str) -> bool | None:
    """Parse a JSON string from the LLM response and extract `is_cache_valid`.

    Tolerates ```json fences (Claude-style). Returns None on any parse
    failure or non-coercible value.
    """
    if not isinstance(content, str):
        return None

    try:
        parsed = parse_json_content(content)
    except ValueError:
        return None

    return _extract_is_cache_valid(parsed)


def _get_workspace_client(runtime_settings=None) -> tuple[WorkspaceClient, str]:
    """Build a WorkspaceClient using the user's OAuth token.

    Resolves the serving endpoint from runtime_settings.validation_model if set,
    else falls back to CACHE_VALIDATION_LLM_ENDPOINT.
    """
    endpoint = CACHE_VALIDATION_LLM_ENDPOINT
    if runtime_settings is not None and getattr(runtime_settings, "validation_model", None):
        endpoint = runtime_settings.validation_model
    if runtime_settings:
        token = runtime_settings.databricks_token
        if not token:
            raise RuntimeError("No user token available for cache validation (X-Forwarded-Access-Token missing)")
        config = Config(host=runtime_settings.databricks_host, token=token, auth_type="pat")
        return WorkspaceClient(config=config), endpoint
    return WorkspaceClient(), endpoint


async def validate_cache_entry(
    incoming_query: str,
    cached_query: str,
    runtime_settings=None,
    space_context: str = "",
) -> bool:
    """
    Use an LLM to validate semantic equivalence between the incoming query
    and the cached query.

    Returns True if semantically equivalent (cache hit confirmed).
    Returns False if the LLM deems them non-equivalent (downgrade to miss).
    On any error, fails open (returns True) to avoid disrupting the service.
    """
    if runtime_settings is not None and not runtime_settings.cache_validation_enabled:
        return True

    try:
        client, endpoint = _get_workspace_client(runtime_settings)

        space_context_section = f"\n\n{space_context}" if space_context else ""
        prompt = (
            "Compare the cached entry with the following question. "
            "If the cached entry is semantically equivalent to the question, "
            "set is_cache_valid to true. Otherwise, set it to false. "
            "Respond ONLY with a JSON object matching this schema: "
            '{"is_cache_valid": <boolean>}.'
            f" {JSON_INSTRUCTION}"
            f"{space_context_section}\n\n"
            f"CACHED ENTRY:\n{cached_query}\n\n"
            f"QUESTION:\n{incoming_query}"
        )

        with tracing.span(
            "gateway.cache.validate",
            span_type="LLM",
            inputs={"incoming": incoming_query, "cached": cached_query},
            attributes={"model": endpoint},
        ) as s:
            try:
                parsed = invoke_json(
                    client,
                    endpoint,
                    [{"role": "user", "content": prompt}],
                    temperature=0.0,
                )
            except ValueError as parse_err:
                s.set_outputs({
                    "is_cache_valid": True,
                    "fallback": "parse_failed",
                    "raw": str(parse_err)[:200],
                })
                logger.warning(
                    "Cache LLM validation: unparseable response — treating as valid hit (%s)",
                    parse_err,
                )
                return True

            is_cache_valid = _extract_is_cache_valid(parsed)

            if is_cache_valid is None:
                s.set_outputs({
                    "is_cache_valid": True,
                    "fallback": "parse_failed",
                    "raw": parsed,
                })
                logger.warning(
                    "Cache LLM validation: unrecognized response shape %r — treating as valid hit",
                    parsed,
                )
                return True

            s.set_outputs({"is_cache_valid": is_cache_valid, "raw": parsed})

        logger.info(
            "Cache LLM validation: result=%s cached=%r... incoming=%r...",
            is_cache_valid,
            cached_query[:60],
            incoming_query[:60],
        )
        return is_cache_valid

    except Exception:
        logger.warning("Cache LLM validation failed — treating as valid hit", exc_info=True)
        return True
