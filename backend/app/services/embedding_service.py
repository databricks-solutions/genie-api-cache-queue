"""
Embedding service - delegates to Databricks or local implementation.
"""

from app.services.embedding_databricks import get_embedding_service

# Get the appropriate embedding service based on configuration
embedding_service = get_embedding_service()
