"""
Query processing pipeline.
Handles the full lifecycle: receive -> check cache -> Genie API -> cache result.
Supports multi-turn conversations via send_message() with context-aware caching.
"""

import logging
import asyncio
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from app.models import QueryStage
import app.services.database as _db
from app.services.queue_service import queue_service
from app.services.embedding_service import embedding_service
from app.services.genie_service import genie_service, GenieRateLimitError, GenieConfigError
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


MAX_RETRIES = 3
RETRY_DELAYS = [5, 15, 30]

# Max previous queries to include in cache context key
CACHE_CONTEXT_LIMIT = 2
# Max previous queries to include in enriched prompt for Genie fallback
ENRICHED_PROMPT_LIMIT = 5


def build_context_text(query_text: str, conversation_history: Optional[List[str]] = None) -> str:
    """Build contextualized text for embedding generation.

    For first messages: returns query_text unchanged.
    For follow-ups: returns "prev1 | prev2 | current" (last N previous + current).
    """
    if not conversation_history:
        return query_text
    recent = conversation_history[-CACHE_CONTEXT_LIMIT:]
    return " | ".join(recent + [query_text])


class QueryProcessor:
    def __init__(self):
        self.active_queries: Dict[str, asyncio.Task] = {}

    async def _call_genie(
        self,
        query_text: str,
        runtime_settings,
        conversation_id: Optional[str] = None,
        conversation_synced: Optional[bool] = None,
        conversation_history: Optional[List[str]] = None,
    ) -> Dict:
        """Decide whether to use start_conversation or send_message.

        - No conversation_id: start_conversation (first message)
        - conversation_id + synced: send_message (continue conversation)
        - conversation_id + not synced: start_conversation with enriched prompt (desync recovery)
        - send_message failure: fallback to start_conversation with enriched prompt
        """
        space_id = runtime_settings.genie_space_id

        if conversation_id and conversation_synced:
            logger.info("Continuing conversation=%s with send_message", conversation_id[:12])
            try:
                return await genie_service.send_message(
                    space_id, conversation_id, query_text, runtime_settings
                )
            except Exception as e:
                logger.warning(
                    "send_message failed (conversation=%s): %s. Falling back to start_conversation.",
                    conversation_id[:12], e
                )
                # Fall through to start_conversation with enriched prompt

        # Build enriched prompt if we have conversation history
        if conversation_history and len(conversation_history) > 0:
            history_text = " | ".join(conversation_history[-ENRICHED_PROMPT_LIMIT:])
            enriched_query = (
                f"Context from previous questions in this conversation: {history_text}\n"
                f"Current question: {query_text}"
            )
            logger.info(
                "Starting new conversation with enriched prompt (history=%d items)",
                len(conversation_history)
            )
            return await genie_service.start_conversation(
                space_id, enriched_query, runtime_settings
            )

        # First message — standard start_conversation
        logger.info("Starting new conversation (first message)")
        return await genie_service.start_conversation(
            space_id, query_text, runtime_settings
        )

    async def process_query(
        self,
        query_id: str,
        query_text: str,
        identity: str,
        runtime_config=None,
        user_token=None,
        user_email=None,
        conversation_id=None,
        conversation_synced=None,
        conversation_history=None,
    ):
        """Process a single query through the entire pipeline."""
        try:
            from app.runtime_config import RuntimeSettings
            runtime_settings = RuntimeSettings(runtime_config, user_token, user_email) if runtime_config else RuntimeSettings(None, user_token, user_email)

            is_follow_up = bool(conversation_history and len(conversation_history) > 0)
            context_text = build_context_text(query_text, conversation_history)

            logger.info("Processing query=%s auth=%s host=%s space=%s follow_up=%s context=%r",
                         query_id[:8], runtime_settings.auth_mode,
                         runtime_settings.databricks_host, runtime_settings.genie_space_id,
                         is_follow_up, context_text[:100])

            self._update_status(query_id, QueryStage.RECEIVED, query_text, identity)
            self._update_status(query_id, QueryStage.CHECKING_CACHE, query_text, identity)

            query_embedding = embedding_service.get_embedding(context_text, runtime_settings)

            try:
                cached_result = await _db.db_service.search_similar_query(
                    query_embedding,
                    identity,
                    runtime_settings.similarity_threshold,
                    runtime_settings.genie_space_id,
                    runtime_settings,
                    shared_cache=runtime_settings.shared_cache
                )
            except Exception as e:
                logger.warning("Cache search failed: %s, continuing without cache", e)
                cached_result = None

            if cached_result:
                cache_id, cached_query, sql_query, similarity = cached_result

                logger.info("Cache HIT: similarity=%.3f sql=%s", similarity, sql_query[:80])

                self._update_status(
                    query_id, QueryStage.CACHE_HIT, query_text, identity,
                    sql_query=sql_query, from_cache=True, similarity=similarity
                )

                self._update_status(
                    query_id, QueryStage.EXECUTING_SQL, query_text, identity,
                    sql_query=sql_query, from_cache=True
                )

                result = await genie_service.execute_sql(sql_query, runtime_settings)

                if result['status'] == 'SUCCEEDED':
                    self._update_status(
                        query_id, QueryStage.COMPLETED, query_text, identity,
                        sql_query=sql_query, result=result['result'], from_cache=True,
                    )
                else:
                    self._update_status(
                        query_id, QueryStage.FAILED, query_text, identity,
                        error=result.get('error', 'SQL execution failed'), from_cache=True
                    )
            else:
                # Cache miss - use Genie API
                self._update_status(query_id, QueryStage.CACHE_MISS, query_text, identity)

                if not queue_service.backend.check_rate_limit(identity, runtime_settings.max_queries_per_minute):
                    position = queue_service.add_to_queue(query_id, {
                        'query_text': query_text,
                        'identity': identity,
                        'query_embedding': query_embedding,
                        'conversation_id': conversation_id,
                        'conversation_synced': conversation_synced,
                        'conversation_history': conversation_history,
                        'runtime_config': runtime_config.model_dump() if runtime_config else None,
                        'user_token': user_token,
                        'user_email': user_email,
                    })

                    self._update_status(
                        query_id, QueryStage.QUEUED, query_text, identity,
                        queue_position=position
                    )
                    return

                self._update_status(query_id, QueryStage.PROCESSING_GENIE, query_text, identity)

                try:
                    genie_result = await self._call_genie(
                        query_text, runtime_settings,
                        conversation_id=conversation_id,
                        conversation_synced=conversation_synced,
                        conversation_history=conversation_history,
                    )

                    if genie_result['status'] == 'COMPLETED':
                        sql_query = genie_result.get('sql_query', '')
                        new_conversation_id = genie_result.get('conversation_id')

                        if sql_query:
                            try:
                                await _db.db_service.save_query_cache(
                                    context_text, query_embedding, sql_query,
                                    identity, runtime_settings.genie_space_id, runtime_settings
                                )
                            except Exception as e:
                                logger.warning("Failed to save to cache: %s", e)

                        self._update_status(
                            query_id, QueryStage.COMPLETED, query_text, identity,
                            sql_query=sql_query, result=genie_result.get('result'),
                            from_cache=False,
                            conversation_id=new_conversation_id,
                        )
                    else:
                        # Genie returned non-COMPLETED — route to queue for retry
                        logger.warning(
                            "Direct Genie call failed for query=%s, routing to queue for retry. error=%s",
                            query_id[:8], genie_result.get('error', 'non-COMPLETED')
                        )
                        queue_service.add_to_queue(query_id, {
                            'query_text': query_text,
                            'identity': identity,
                            'query_embedding': query_embedding,
                            'conversation_id': conversation_id,
                            'conversation_synced': conversation_synced,
                            'conversation_history': conversation_history,
                            '_retries': 1,
                            'runtime_config': runtime_config.model_dump() if runtime_config else None,
                            'user_token': user_token,
                            'user_email': user_email,
                        })
                        self._update_status(query_id, QueryStage.QUEUED, query_text, identity)

                except GenieRateLimitError as rate_err:
                    # Genie API returned 429 — queue with API's Retry-After delay
                    logger.warning(
                        "Genie 429 for direct query=%s, queuing with %ds delay",
                        query_id[:8], rate_err.retry_after
                    )
                    queue_service.add_to_queue(query_id, {
                        'query_text': query_text,
                        'identity': identity,
                        'query_embedding': query_embedding,
                        'conversation_id': conversation_id,
                        'conversation_synced': conversation_synced,
                        'conversation_history': conversation_history,
                        '_retries': 0,
                        '_delay': rate_err.retry_after,
                        'runtime_config': runtime_config.model_dump() if runtime_config else None,
                        'user_token': user_token,
                        'user_email': user_email,
                    })
                    self._update_status(query_id, QueryStage.QUEUED, query_text, identity)

                except GenieConfigError as cfg_err:
                    # Non-retryable config error (404, 401, 403) — fail immediately
                    logger.error(
                        "Genie config error for query=%s: %s (not retryable)",
                        query_id[:8], cfg_err
                    )
                    self._update_status(
                        query_id, QueryStage.FAILED, query_text, identity,
                        error=str(cfg_err)
                    )

                except Exception as genie_exc:
                    # Transient errors (network, 5xx, timeout) — route to queue for retry
                    logger.warning(
                        "Direct Genie call exception for query=%s: %s, routing to queue for retry",
                        query_id[:8], genie_exc
                    )
                    queue_service.add_to_queue(query_id, {
                        'query_text': query_text,
                        'identity': identity,
                        'query_embedding': query_embedding,
                        'conversation_id': conversation_id,
                        'conversation_synced': conversation_synced,
                        'conversation_history': conversation_history,
                        '_retries': 1,
                        'runtime_config': runtime_config.model_dump() if runtime_config else None,
                        'user_token': user_token,
                        'user_email': user_email,
                    })
                    self._update_status(query_id, QueryStage.QUEUED, query_text, identity)

        except Exception as e:
            self._update_status(
                query_id, QueryStage.FAILED, query_text, identity, error=str(e)
            )
        finally:
            if query_id in self.active_queries:
                del self.active_queries[query_id]

    def _update_status(self, query_id, stage, query_text, identity, **kwargs):
        """Update query status."""
        now = datetime.now().isoformat()
        existing_status = queue_service.get_query_status(query_id)

        status_data = {
            'query_id': query_id,
            'query_text': query_text,
            'identity': identity,
            'stage': stage.value,
            'updated_at': now,
            'created_at': existing_status.get('created_at', now) if existing_status else now,
            **kwargs
        }
        queue_service.save_query_status(query_id, status_data)

    def submit_query(
        self, query_text, identity, runtime_config=None,
        user_token=None, user_email=None,
        conversation_id=None, conversation_synced=None,
        conversation_history=None,
    ) -> str:
        """Submit a new query for processing."""
        query_id = str(uuid.uuid4())

        task = asyncio.create_task(
            self.process_query(
                query_id, query_text, identity, runtime_config,
                user_token, user_email,
                conversation_id=conversation_id,
                conversation_synced=conversation_synced,
                conversation_history=conversation_history,
            )
        )
        self.active_queries[query_id] = task

        self._update_status(query_id, QueryStage.RECEIVED, query_text, identity)

        return query_id

    async def process_queue(self):
        """Background task to process queued queries with retry and exponential backoff."""
        while True:
            try:
                queued_item = queue_service.get_from_queue()

                if queued_item:
                    query_id = queued_item['query_id']
                    query_text = queued_item['query_text']
                    identity = queued_item['identity']
                    query_embedding = queued_item.get('query_embedding')
                    retries = queued_item.get('_retries', 0)
                    conv_id = queued_item.get('conversation_id')
                    conv_synced = queued_item.get('conversation_synced')
                    conv_history = queued_item.get('conversation_history')
                    raw_runtime_config = queued_item.get('runtime_config')
                    user_token = queued_item.get('user_token')
                    user_email = queued_item.get('user_email')

                    context_text = build_context_text(query_text, conv_history)

                    self._update_status(query_id, QueryStage.PROCESSING_GENIE, query_text, identity)

                    from app.runtime_config import RuntimeSettings
                    from app.models import RuntimeConfig
                    rc = RuntimeConfig(**raw_runtime_config) if raw_runtime_config else None
                    runtime_settings = RuntimeSettings(rc, user_token, user_email)

                    try:
                        genie_result = await self._call_genie(
                            query_text, runtime_settings,
                            conversation_id=conv_id,
                            conversation_synced=conv_synced,
                            conversation_history=conv_history,
                        )

                        if genie_result['status'] == 'COMPLETED':
                            sql_query = genie_result.get('sql_query', '')
                            new_conversation_id = genie_result.get('conversation_id')

                            if sql_query and query_embedding:
                                try:
                                    await _db.db_service.save_query_cache(
                                        context_text, query_embedding, sql_query,
                                        identity, runtime_settings.genie_space_id, runtime_settings
                                    )
                                except Exception as e:
                                    logger.warning("Failed to save to cache: %s", e)

                            self._update_status(
                                query_id, QueryStage.COMPLETED, query_text, identity,
                                sql_query=sql_query, result=genie_result.get('result'),
                                from_cache=False,
                                conversation_id=new_conversation_id,
                            )
                        else:
                            # Genie returned non-COMPLETED — retry or fail
                            if retries < MAX_RETRIES:
                                delay = RETRY_DELAYS[retries]
                                logger.warning("Re-queuing query=%s retry=%d/%d delay=%ds reason=%s",
                                               query_id[:8], retries + 1, MAX_RETRIES, delay,
                                               genie_result.get('error', 'non-COMPLETED'))
                                queue_service.add_to_queue(query_id, {
                                    'query_text': query_text,
                                    'identity': identity,
                                    'query_embedding': query_embedding,
                                    'conversation_id': conv_id,
                                    'conversation_synced': conv_synced,
                                    'conversation_history': conv_history,
                                    '_retries': retries + 1,
                                    'runtime_config': raw_runtime_config,
                                    'user_token': user_token,
                                    'user_email': user_email,
                                })
                                self._update_status(query_id, QueryStage.QUEUED, query_text, identity)
                                await asyncio.sleep(delay)
                            else:
                                logger.error("Retries exhausted for query=%s after %d attempts", query_id[:8], MAX_RETRIES)
                                self._update_status(
                                    query_id, QueryStage.FAILED, query_text, identity,
                                    error=f"Failed after {MAX_RETRIES} retries: {genie_result.get('error', 'Genie API failed')}"
                                )

                    except GenieRateLimitError as rate_err:
                        # Genie API returned 429 — use API's Retry-After delay
                        delay = rate_err.retry_after
                        logger.warning("Genie 429 for query=%s, waiting %ds (API Retry-After)", query_id[:8], delay)
                        queue_service.add_to_queue(query_id, {
                            'query_text': query_text,
                            'identity': identity,
                            'query_embedding': query_embedding,
                            'conversation_id': conv_id,
                            'conversation_synced': conv_synced,
                            'conversation_history': conv_history,
                            '_retries': retries,
                            'runtime_config': raw_runtime_config,
                            'user_token': user_token,
                            'user_email': user_email,
                        })
                        self._update_status(query_id, QueryStage.QUEUED, query_text, identity)
                        await asyncio.sleep(delay)

                    except GenieConfigError as cfg_err:
                        # Non-retryable config error (404, 401, 403) — fail immediately
                        logger.error(
                            "Genie config error for queued query=%s: %s (not retryable)",
                            query_id[:8], cfg_err
                        )
                        self._update_status(
                            query_id, QueryStage.FAILED, query_text, identity,
                            error=str(cfg_err)
                        )

                    except Exception as inner_e:
                        # Transient errors (network, 5xx, timeout) — retry or fail
                        if retries < MAX_RETRIES:
                            delay = RETRY_DELAYS[retries]
                            logger.warning("Re-queuing query=%s retry=%d/%d delay=%ds error=%s",
                                           query_id[:8], retries + 1, MAX_RETRIES, delay, inner_e)
                            queue_service.add_to_queue(query_id, {
                                'query_text': query_text,
                                'identity': identity,
                                'query_embedding': query_embedding,
                                'conversation_id': conv_id,
                                'conversation_synced': conv_synced,
                                'conversation_history': conv_history,
                                '_retries': retries + 1,
                                'runtime_config': raw_runtime_config,
                                'user_token': user_token,
                                'user_email': user_email,
                            })
                            self._update_status(query_id, QueryStage.QUEUED, query_text, identity)
                            await asyncio.sleep(delay)
                        else:
                            logger.error("Retries exhausted for query=%s after %d attempts: %s", query_id[:8], MAX_RETRIES, inner_e)
                            self._update_status(
                                query_id, QueryStage.FAILED, query_text, identity,
                                error=f"Failed after {MAX_RETRIES} retries: {str(inner_e)}"
                            )
                else:
                    await asyncio.sleep(1)

            except Exception as e:
                logger.error("Error processing queue: %s", e)
                await asyncio.sleep(5)


query_processor = QueryProcessor()
