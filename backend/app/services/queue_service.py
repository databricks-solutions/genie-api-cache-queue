"""
Queue/cache abstraction layer using in-memory storage.
"""

from typing import Optional, List
from datetime import datetime
from app.config import get_settings
from app.services.storage_local import get_local_queue

settings = get_settings()
_queue_backend = get_local_queue()


class QueueService:
    """
    Unified queue/cache service.
    Uses in-memory storage (sufficient for single-instance Databricks Apps).
    """

    def __init__(self):
        self.backend = _queue_backend

    def check_rate_limit(self, identity: str) -> bool:
        """Check if the rate limit has been exceeded."""
        return self.backend.check_rate_limit(identity, settings.max_queries_per_minute)

    def add_to_queue(self, query_id: str, query_data: dict) -> int:
        """Add a query to the processing queue."""
        return self.backend.add_to_queue(query_id, query_data)

    def get_from_queue(self) -> Optional[dict]:
        """Get the next query from the queue."""
        return self.backend.get_from_queue()

    def get_queue_length(self) -> int:
        """Get the current queue length."""
        return self.backend.get_queue_length()

    def get_all_queued(self) -> List[dict]:
        """Get all queued queries without removing them."""
        return self.backend.get_all_queued()

    def save_query_status(self, query_id: str, status_data: dict):
        """Save query status information."""
        self.backend.save_query_status(query_id, status_data)

    def get_query_status(self, query_id: str) -> Optional[dict]:
        """Get query status information."""
        return self.backend.get_query_status(query_id)

    def update_query_stage(self, query_id: str, stage: str, **kwargs):
        """Update the stage of a query."""
        self.backend.update_query_stage(query_id, stage, **kwargs)


queue_service = QueueService()
