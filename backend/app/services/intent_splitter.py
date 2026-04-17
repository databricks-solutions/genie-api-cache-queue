"""
Intent splitting service.

When a user changes topic mid-conversation, the cache context text spans multiple
distinct intents. Searching the cache with mixed-intent context produces lower
similarity scores and reduces cache hit rates.

This service uses an LLM to detect intent shifts in the conversation context and
returns only the portion belonging to the latest intent, so downstream embedding
and cache lookup operates on a single coherent question.
"""

import logging

from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Default Databricks Foundation Model endpoint used for intent splitting.
# Can be overridden per-gateway or globally via RuntimeSettings.intent_split_model.
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
- If the entire conversation is one continuous intent, return it unchanged.
- Preserve the original wording exactly — do not paraphrase, translate, or modify.
- If you find a clear intent shift, return only the relevant portion of the conversation, with no explanation.

{space_context}

CONVERSATION:
{context_text}"""


def _get_workspace_client(runtime_settings=None) -> tuple[WorkspaceClient, str]:
    """Build a WorkspaceClient respecting the current auth mode.

    Resolves the serving endpoint from runtime_settings.intent_split_model if set,
    else falls back to INTENT_SPLIT_LLM_ENDPOINT.
    """
    endpoint = INTENT_SPLIT_LLM_ENDPOINT
    if runtime_settings is not None and getattr(runtime_settings, "intent_split_model", None):
        endpoint = runtime_settings.intent_split_model
    if runtime_settings:
        token = runtime_settings.databricks_token
        if not token:
            raise RuntimeError("User Auth mode requires a Personal Access Token")
        config = Config(host=runtime_settings.databricks_host, token=token, auth_type="pat")
        client = WorkspaceClient(config=config)
    else:
        client = WorkspaceClient()
    return client, endpoint


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

        result = response["choices"][0]["message"]["content"].strip()

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
