"""
LLM-based cache validation service.

Validates that a cached query is semantically equivalent to the incoming query.
Uses WorkspaceClient.serving_endpoints.query with structured JSON output to avoid
false cache hits from vector similarity alone (e.g., "Revenue in Q1" vs "Revenue in Q2").
"""

import json
import logging

from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

from app.config import get_settings
from app.services import tracing

logger = logging.getLogger(__name__)
settings = get_settings()

# Default Databricks Foundation Model endpoint used for validation.
# Can be overridden per-gateway or globally via RuntimeSettings.validation_model.
CACHE_VALIDATION_LLM_ENDPOINT = "databricks-llama-4-maverick"


def _parse_validation_result(result: dict) -> bool | None:
    """
    Extract is_cache_valid from the parsed JSON response.

    Handles native booleans, string booleans ("true"/"false"), and other
    truthy types. Returns None if the key is missing so the caller can
    decide how to handle the ambiguity.
    """
    value = result.get("is_cache_valid")
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value)


def _get_workspace_client(runtime_settings=None) -> tuple[WorkspaceClient, str]:
    """Build a WorkspaceClient using user's OAuth token (X-Forwarded-Access-Token).

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
            "Do not add any additional text or explanation."
            'Respond only with valid JSON matching this schema: {"is_cache_valid": <boolean>}. '
            f'Example: {{"is_cache_valid": true}}{space_context_section}\n\n'
            f"CACHED ENTRY:\n{cached_query}\n\n"
            f"QUESTION:\n{incoming_query}"
        )

        with tracing.span(
            "gateway.cache.validate",
            span_type="LLM",
            inputs={"incoming": incoming_query, "cached": cached_query},
            attributes={"model": endpoint},
        ) as s:
            response = client.api_client.do(
                "POST",
                f"/serving-endpoints/{endpoint}/invocations",
                body={"messages": [{"role": "user", "content": prompt}]}
            )

            content = response["choices"][0]["message"]["content"]

            # Strip markdown fences the LLM sometimes wraps around JSON
            # (e.g. ```json\n{"is_cache_valid": true}\n```). Mirrors the
            # robust-parse pattern in question_normalizer.
            stripped = content.strip()
            if stripped.startswith("```"):
                stripped = stripped.lstrip("`")
                if stripped.startswith("json"):
                    stripped = stripped[4:]
                if "```" in stripped:
                    stripped = stripped[: stripped.rfind("```")]
                stripped = stripped.strip()

            try:
                result = json.loads(stripped)
            except json.JSONDecodeError:
                # Don't let a parse failure ERROR out the span — fail open is
                # expected behavior, not a tracing-level error. Log the raw
                # content so the trace still has the diagnostic.
                s.set_outputs({"is_cache_valid": True, "fallback": "json_parse_error", "raw": content[:200]})
                logger.warning("Cache LLM validation: unparseable JSON %r — treating as valid hit", content[:120])
                return True

            is_cache_valid = _parse_validation_result(result)
            s.set_outputs({"is_cache_valid": is_cache_valid, "raw": content})

        if is_cache_valid is None:
            logger.warning(
                "Cache LLM validation: missing is_cache_valid key in response %r — treating as valid hit",
                content[:120],
            )
            return True

        logger.info(
            "Cache LLM validation: result=%s cached=%r... incoming=%r...",
            is_cache_valid,
            cached_query[:60],
            incoming_query[:60],
        )
        return is_cache_valid

    except Exception as exc:
        logger.warning("Cache LLM validation failed — treating as valid hit: %s", exc)
        return True
