"""
Question normalization service.

Improves semantic cache hit rates by normalizing input questions before embedding
generation and cache storage. Applies string normalization (lowercase) followed by
LLM-based semantic normalization into a structured business requirement format.
"""

import json
import logging

from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Databricks Foundation Model endpoint used for normalization.
QUESTION_NORMALIZATION_LLM_ENDPOINT = "databricks-llama-4-maverick"

_NORMALIZATION_PROMPT_TEMPLATE = """\
{space_context}

Analyze the following business question and rewrite it as a structured business requirement.
Preserve the original language and the exact terms used in the question (ie. do not translate "produto" to "product"; do not change "quantidade de produtos" to "count").
Keep in mind that you will receive a multi-turn conversation delimited by "|", so try to understand the full intent of the latest turn.

Respond ONLY with valid JSON matching exactly this schema — no explanation, no markdown:
{{
  "metrics": ["<measurable value, e.g. revenue, quantity, avg order value>", ...],
  "aggregations": ["<grouping dimension, e.g. month, region, product>", ...],
  "filters": ["<condition limiting the data, e.g. year=2024, category=electronics>", ...],
  "ordering": ["<sort instruction, e.g. descending by revenue>", ...],
  "limit": <integer row limit if specified, otherwise null>
}}

Do NOT translate the terms to any other language. Do NOT change the terms used in the question.
Do NOT add any additional text or explanation. Do NOT add markdown like ```json or ```. Do NOT add line breaks.

QUESTION:
{question}"""


def _get_workspace_client(runtime_settings=None) -> tuple[WorkspaceClient, str]:
    """Build a WorkspaceClient using user's OAuth token (X-Forwarded-Access-Token)."""
    if runtime_settings:
        token = runtime_settings.databricks_token
        if not token:
            raise RuntimeError("No user token available for question normalization (X-Forwarded-Access-Token missing)")
        config = Config(host=runtime_settings.databricks_host, token=token, auth_type="pat")
        return WorkspaceClient(config=config), QUESTION_NORMALIZATION_LLM_ENDPOINT
    return WorkspaceClient(), QUESTION_NORMALIZATION_LLM_ENDPOINT


async def normalize_question(query_text: str, runtime_settings=None, space_context: str = "") -> str:
    """
    Normalize an input question to improve semantic cache hit rates.

    Step 1 — String normalization: lowercases and strips the input.
    Step 2 — LLM normalization: rewrites the question as a structured business
             requirement and returns a string concatenating all keys and values
             from the result JSON (e.g. "metrics: revenue | filters: year=2024").

    On any error, fails open and returns the string-normalized text so the
    pipeline is never disrupted by normalization failures.
    """
    # Step 1: string normalization
    string_normalized = query_text.lower().strip()

    if runtime_settings is not None and not runtime_settings.question_normalization_enabled:
        return string_normalized

    # Step 2: LLM normalization
    try:
        client, endpoint = _get_workspace_client(runtime_settings)

        prompt = _NORMALIZATION_PROMPT_TEMPLATE.format(question=string_normalized, space_context=space_context)

        response = client.api_client.do(
            "POST",
            f"/serving-endpoints/{endpoint}/invocations",
            body={"messages": [{"role": "user", "content": prompt}]},
        )

        content = response["choices"][0]["message"]["content"]

        try:
            # Strip markdown code fences the LLM sometimes wraps around JSON
            stripped = content.strip()
            if stripped.startswith("```"):
                stripped = stripped.lstrip("`")
                if stripped.startswith("json"):
                    stripped = stripped[4:]
                # Remove closing fence (may be malformed, e.g. missing newline before ```)
                if "```" in stripped:
                    stripped = stripped[: stripped.rfind("```")]
                content = stripped.strip()
            result = json.loads(content)
        except Exception as e:
            import traceback
            logger.warning("Question normalizer: traceback=%s", traceback.format_exc())
            logger.warning(
                "Question normalizer: unparseable result in response %r — falling back to lowercased input",
                content[:120],
            )
            return string_normalized

        parts = []
        for key, value in result.items():
            if isinstance(value, list):
                if not value:  # skip if the list is empty
                    continue
                str_value = ", ".join(str(v) for v in value)
                parts.append(f"{key}: {str_value}")
            else:
                if value is None or (isinstance(value, str) and value.strip() == ""):  # skip if None or empty string
                    continue
                str_value = str(value)
                parts.append(f"{key}: {str_value}")

        canonical = " | ".join(parts)

        if not canonical:
            logger.warning("Question normalizer: canonical is empty — falling back to lowercased input")
            return string_normalized

        logger.info(
            "Question normalizer: original=%r... canonical=%r...",
            query_text[:60],
            canonical[:60],
        )
        return canonical

    except Exception as exc:
        logger.warning("Question normalization failed — falling back to lowercased input: %s", exc)
        return string_normalized
