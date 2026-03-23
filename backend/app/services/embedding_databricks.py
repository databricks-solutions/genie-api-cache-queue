"""
Databricks Foundation Model API for embeddings.
Uses Databricks SDK for clean, authenticated API calls.
"""

import logging
from typing import List, Optional
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class DatabricksEmbeddingService:
    """
    Embedding service using Databricks SDK.
    Supports Foundation Model endpoints like databricks-gte-large-en.
    """

    def __init__(self):
        self.default_endpoint = settings.databricks_embedding_endpoint

    def _get_workspace_client(self, runtime_settings=None) -> tuple[WorkspaceClient, str]:
        """Get WorkspaceClient using user's OAuth token (X-Forwarded-Access-Token)."""
        if runtime_settings:
            token = runtime_settings.databricks_token
            if not token:
                raise RuntimeError("No user token available for embeddings (X-Forwarded-Access-Token missing)")
            config = Config(host=runtime_settings.databricks_host, token=token, auth_type="pat")
            return WorkspaceClient(config=config), runtime_settings.databricks_embedding_endpoint
        config = Config(host=settings.databricks_host, token=settings.databricks_token, auth_type="pat")
        return WorkspaceClient(config=config), self.default_endpoint

    def get_embedding(self, text: str, runtime_settings=None) -> List[float]:
        """Generate embedding for a single text using Databricks SDK."""
        return self.get_embeddings([text], runtime_settings)[0]

    def get_embeddings(self, texts: List[str], runtime_settings=None) -> List[List[float]]:
        """Generate embeddings for multiple texts using Databricks SDK."""
        try:
            client, endpoint = self._get_workspace_client(runtime_settings)

            logger.info("Embedding API call: endpoint=%s texts=%d", endpoint, len(texts))

            response = client.serving_endpoints.query(
                name=endpoint,
                input=texts
            )

            embeddings = None
            response_dict = response.as_dict() if hasattr(response, 'as_dict') else None

            if hasattr(response, 'predictions') and response.predictions is not None:
                embeddings = response.predictions
            elif hasattr(response, 'data') and response.data is not None:
                embeddings = [item.embedding if hasattr(item, 'embedding') else item.get("embedding")
                             for item in response.data]
            elif response_dict:
                if 'predictions' in response_dict and response_dict['predictions']:
                    embeddings = response_dict['predictions']
                elif 'data' in response_dict and response_dict['data']:
                    data = response_dict['data']
                    if isinstance(data, list) and len(data) > 0:
                        if isinstance(data[0], dict) and 'embedding' in data[0]:
                            embeddings = [item['embedding'] for item in data]
                        else:
                            embeddings = data

            if embeddings is None:
                raise ValueError(
                    f"Could not extract embeddings from response type={type(response)}"
                )

            logger.info("Got %d embeddings", len(embeddings))
            return embeddings

        except Exception:
            logger.exception("Error calling Databricks embedding API")
            raise


class LocalEmbeddingService:
    """
    Local embedding service using sentence-transformers.
    Used as fallback when Databricks API is not available.
    """

    def __init__(self):
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(settings.local_embedding_model)
        except ImportError:
            raise ImportError(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )

    def get_embedding(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        embedding = self.model.encode(text)
        return embedding.tolist()

    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        embeddings = self.model.encode(texts)
        return embeddings.tolist()


def get_embedding_service():
    """Get embedding service based on configuration."""
    if settings.embedding_provider == "databricks":
        return DatabricksEmbeddingService()
    else:
        return LocalEmbeddingService()


embedding_service = get_embedding_service()
