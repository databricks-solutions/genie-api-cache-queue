"""
Databricks Genie API client.
Handles conversation lifecycle, message polling, and SQL execution.
"""

import logging
import httpx
import asyncio
from typing import Optional, Dict
from app.config import get_settings
from app.auth import ensure_https

logger = logging.getLogger(__name__)
settings = get_settings()


class GenieRateLimitError(Exception):
    """Raised when Genie API returns 429 Too Many Requests."""
    def __init__(self, retry_after: float = 60.0):
        self.retry_after = retry_after
        super().__init__(f"Genie API rate limited. Retry after {retry_after}s")


class GenieService:
    def __init__(self):
        host = ensure_https(settings.databricks_host)
        self.default_base_url = f"{host}/api/2.0/genie" if host else ""
        self.default_headers = {
            "Authorization": f"Bearer {settings.databricks_token}",
            "Content-Type": "application/json"
        } if settings.databricks_token else {}

    def _get_config(self, runtime_settings=None):
        """Get configuration (runtime or default)."""
        if runtime_settings:
            host = ensure_https(runtime_settings.databricks_host)
            token = runtime_settings.databricks_token

            if not token or (isinstance(token, str) and token.strip() == ""):
                logger.warning("Empty token in runtime_settings (auth_mode=%s)", runtime_settings.auth_mode)

            return (
                f"{host}/api/2.0/genie",
                {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
            )
        return self.default_base_url, self.default_headers

    async def start_conversation(self, space_id: str, query: str, runtime_settings=None) -> Dict:
        """
        Start a new conversation with Genie (creates conversation and sends first message).
        Reference: https://docs.databricks.com/api/workspace/genie/startconversation
        """
        base_url, headers = self._get_config(runtime_settings)
        url = f"{base_url}/spaces/{space_id}/start-conversation"
        payload = {"content": query}

        logger.info("Genie start-conversation space=%s query=%r", space_id, query[:80])

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=30.0)

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 60))
                logger.warning("Genie API rate limited (429). Retry-After: %ss", retry_after)
                raise GenieRateLimitError(retry_after)

            if not response.is_success:
                logger.error("Genie API error %d: %s", response.status_code, response.text[:200])

            response.raise_for_status()
            data = response.json()

            conversation_id = data.get("conversation_id")
            message_id = data.get("message_id")

            return await self._poll_message(space_id, conversation_id, message_id, runtime_settings)

    async def send_message(
        self,
        space_id: str,
        conversation_id: str,
        query: str,
        runtime_settings=None
    ) -> Dict:
        """
        Send a message to an existing Genie conversation.
        Reference: https://docs.databricks.com/api/workspace/genie/createmessage
        """
        base_url, headers = self._get_config(runtime_settings)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{base_url}/spaces/{space_id}/conversations/{conversation_id}/messages",
                headers=headers,
                json={"content": query},
                timeout=30.0
            )

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 60))
                logger.warning("Genie API rate limited (429) on send_message. Retry-After: %ss", retry_after)
                raise GenieRateLimitError(retry_after)

            response.raise_for_status()
            message_data = response.json()
            message_id = message_data.get("message_id")

            return await self._poll_message(space_id, conversation_id, message_id, runtime_settings)

    async def _poll_message(
        self,
        space_id: str,
        conversation_id: str,
        message_id: str,
        runtime_settings=None
    ) -> Dict:
        """
        Poll for message completion.
        Reference: https://docs.databricks.com/api/workspace/genie/getmessage
        """
        base_url, headers = self._get_config(runtime_settings)

        async with httpx.AsyncClient() as client:
            max_attempts = 60
            for attempt in range(max_attempts):
                await asyncio.sleep(2)

                response = await client.get(
                    f"{base_url}/spaces/{space_id}/conversations/{conversation_id}/messages/{message_id}",
                    headers=headers,
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()

                status = data.get("status")

                if status == "COMPLETED":
                    sql_query = None
                    attachments = data.get("attachments", [])
                    for attachment in attachments:
                        query_obj = attachment.get("query")
                        if query_obj:
                            sql_query = query_obj.get("query") or query_obj.get("sql")
                            break

                    return {
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "status": "COMPLETED",
                        "attachments": attachments,
                        "sql_query": sql_query,
                        "result": attachments
                    }

                elif status in ["FAILED", "CANCELLED"]:
                    error_obj = data.get("error", {})
                    return {
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "status": status,
                        "error": error_obj.get("error", "Unknown error"),
                        "error_type": error_obj.get("type")
                    }

                elif status == "QUERY_RESULT_EXPIRED":
                    return {
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "status": status,
                        "error": "Query result expired. Please rerun the query."
                    }

            return {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "status": "TIMEOUT",
                "error": "Query timed out after 120 seconds"
            }

    async def execute_sql(self, sql_query: str, runtime_settings=None) -> Dict:
        """Execute SQL query against warehouse."""
        rs = runtime_settings if runtime_settings else settings

        host = ensure_https(rs.databricks_host)
        sql_url = f"{host}/api/2.0/sql/statements"
        headers = {
            "Authorization": f"Bearer {rs.databricks_token}",
            "Content-Type": "application/json"
        } if runtime_settings else self.default_headers

        logger.info("Executing SQL via warehouse=%s query=%s", rs.sql_warehouse_id, sql_query[:100])

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    sql_url,
                    headers=headers,
                    json={
                        "statement": sql_query,
                        "warehouse_id": rs.sql_warehouse_id,
                        "wait_timeout": "30s"
                    },
                    timeout=60.0
                )
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as e:
                logger.error("SQL warehouse error %d: %s", e.response.status_code, e.response.text[:200])
                raise

            statement_id = data.get("statement_id")
            status = data.get("status", {}).get("state")

            if status not in ["SUCCEEDED", "FAILED", "CANCELED"]:
                max_attempts = 30
                for attempt in range(max_attempts):
                    await asyncio.sleep(1)

                    status_response = await client.get(
                        f"{host}/api/2.0/sql/statements/{statement_id}",
                        headers=headers,
                        timeout=30.0
                    )
                    status_response.raise_for_status()
                    data = status_response.json()
                    status = data.get("status", {}).get("state")

                    if status in ["SUCCEEDED", "FAILED", "CANCELED"]:
                        break

            return {
                "statement_id": statement_id,
                "status": status,
                "result": data.get("result"),
                "error": data.get("status", {}).get("error")
            }


genie_service = GenieService()
