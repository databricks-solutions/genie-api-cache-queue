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


class GenieConfigError(Exception):
    """Raised for non-retryable errors (404 space not found, 401 unauthorized, 403 forbidden)."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Genie API {status_code}: {detail}")


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
                logger.warning("Empty authentication token — Genie call will fail")

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

        logger.info("Genie start-conversation space=%s query=%r url=%s token_len=%d", space_id, query[:80], url, len(headers.get("Authorization", "")) if headers else 0)

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=30.0)

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 60))
                logger.warning("Genie API rate limited (429). Retry-After: %ss", retry_after)
                raise GenieRateLimitError(retry_after)

            if response.status_code in (401, 403, 404):
                detail = {
                    401: f"Unauthorized. Check your token/credentials for {space_id}",
                    403: f"Forbidden. The service principal or user lacks access to Genie Space {space_id}",
                    404: f"Genie Space '{space_id}' not found. Verify the Space ID exists on this workspace",
                }[response.status_code]
                logger.error("Genie config error %d: %s — %s", response.status_code, detail, response.text[:200])
                raise GenieConfigError(response.status_code, detail)

            if not response.is_success:
                body = response.text[:500]
                logger.error("Genie API error %d: %s", response.status_code, body)
                raise Exception(f"Genie API {response.status_code}: {body}")
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

            if response.status_code in (401, 403, 404):
                detail = {
                    401: f"Unauthorized. Check your token/credentials",
                    403: f"Forbidden. Lacks access to Genie Space {space_id}",
                    404: f"Conversation {conversation_id} or Space {space_id} not found",
                }[response.status_code]
                logger.error("Genie config error %d on send_message: %s", response.status_code, detail)
                raise GenieConfigError(response.status_code, detail)

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

            # Extract columns from manifest and combine with data_array
            manifest = data.get("manifest", {})
            schema_cols = manifest.get("schema", {}).get("columns", [])
            columns = [c.get("name", "") for c in schema_cols]
            raw_result = data.get("result") or {}
            data_array = raw_result.get("data_array", []) if isinstance(raw_result, dict) else []
            row_count = raw_result.get("row_count", len(data_array)) if isinstance(raw_result, dict) else 0

            structured_result = {
                "columns": columns,
                "data_array": data_array,
                "row_count": row_count,
            } if status == "SUCCEEDED" else None

            return {
                "statement_id": statement_id,
                "status": status,
                "result": structured_result,
                "error": data.get("status", {}).get("error")
            }


genie_service = GenieService()
