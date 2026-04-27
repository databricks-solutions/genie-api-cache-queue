"""
Intent splitting service.

When a user changes topic mid-conversation, the cache context text spans multiple
distinct intents. Searching the cache with mixed-intent context produces lower
similarity scores and reduces cache hit rates.

This service uses an LLM to detect intent shifts in the conversation context and
returns only the portion belonging to the latest intent, so downstream embedding
and cache lookup operates on a single coherent question.
"""

import json
import logging

from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

INTENT_SPLIT_LLM_ENDPOINT = "databricks-llama-4-maverick"

_INTENT_SPLIT_PROMPT_TEMPLATE = """\
You receive a business conversation context that may contain one or more questions or \
requests from a user.
Your task: identify if there is an intent shift — a point where the user clearly moved \
to a different subject, metric, or data domain — and return only the portion of the \
conversation that belongs to the *latest* intent.

Rules:
- Refinements of the same topic (adding filters, aggregations, ordering, limits, \
drill-downs) are NOT intent shifts — they are continuations of the same intent.
- An intent shift happens when a sentence clearly is not additive to the previous \
sentences and clearly switches to a different subject.
- If the entire conversation is one continuous intent, return the conversation unchanged.
- Preserve the original wording exactly — do not paraphrase, translate, or modify.

Respond ONLY with valid JSON matching exactly this schema — no explanation, no markdown:
{{
  "latest_intent": "<the portion of the conversation belonging to the latest intent, verbatim>"
}}

Do NOT translate or change the original wording. Do NOT add any additional text or explanation. \
Do NOT add markdown like ```json or ```. Do NOT add line breaks outside of the JSON string value.

{space_context}

CONVERSATION:
{context_text}"""


def _get_workspace_client(runtime_settings=None) -> tuple[WorkspaceClient, str]:
    """Build a WorkspaceClient respecting the current auth mode."""
    if runtime_settings:
        token = runtime_settings.databricks_token
        if not token:
            raise RuntimeError("User Auth mode requires a Personal Access Token")
        config = Config(host=runtime_settings.databricks_host, token=token, auth_type="pat")
        client = WorkspaceClient(config=config)
    else:
        client = WorkspaceClient()
    return client, INTENT_SPLIT_LLM_ENDPOINT


async def split_by_intent(context_text: str, runtime_settings=None, space_context: str = "") -> str:
    """
    Given a conversation context string, detect intent shifts and return only the
    portion belonging to the latest intent.

    On any LLM or parsing error, fails open and returns the original context_text.
    """
    try:
        client, endpoint = _get_workspace_client(runtime_settings)

        prompt = _INTENT_SPLIT_PROMPT_TEMPLATE.format(context_text=context_text, space_context=space_context)

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
            parsed = json.loads(content)
        except Exception:
            import traceback
            logger.warning("Intent splitter: traceback=%s", traceback.format_exc())
            logger.warning(
                "Intent splitter: unparseable result in response %r — returning original context",
                content[:120],
            )
            return context_text

        result = parsed.get("latest_intent")
        if not isinstance(result, str):
            logger.warning(
                "Intent splitter: missing or non-string 'latest_intent' in %r — returning original context",
                parsed,
            )
            return context_text

        result = result.strip()
        if not result:
            logger.warning("Intent splitter: empty result — returning original context")
            return context_text

        logger.info(
            "Intent splitter: original=%r... result=%r...",
            context_text[:60],
            result[:60],
        )
        return result

    except Exception as exc:
        logger.warning("Intent split failed — returning original context: %s", exc)
        return context_text
