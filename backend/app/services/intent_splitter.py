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
- If the entire conversation is one continuous intent, return the entire conversation \
verbatim as the latest intent.
- Preserve the original wording exactly — do not paraphrase, translate, or modify.

Respond ONLY with a JSON object matching exactly this schema:
{{"latest_intent": "<the portion of the conversation belonging to the latest intent, verbatim>"}}

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


def _parse_latest_intent(content: str) -> str | None:
    """Parse the LLM response and extract the `latest_intent` field.

    Returns the trimmed string on success, or None on any parse failure
    (invalid JSON, missing key, non-string value, empty after strip).
    """
    if not isinstance(content, str):
        return None

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, dict):
        return None

    result = parsed.get("latest_intent")
    if not isinstance(result, str):
        return None

    result = result.strip()
    return result or None


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
            body={
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
        )

        content = response["choices"][0]["message"]["content"]
        result = _parse_latest_intent(content)

        if result is None:
            preview = content[:120] if isinstance(content, str) else content
            logger.warning(
                "Intent splitter: unparseable response %r — returning original context",
                preview,
            )
            return context_text

        logger.info(
            "Intent splitter: original=%r... result=%r...",
            context_text[:60],
            result[:60],
        )
        return result

    except Exception:
        logger.warning("Intent split failed — returning original context", exc_info=True)
        return context_text
