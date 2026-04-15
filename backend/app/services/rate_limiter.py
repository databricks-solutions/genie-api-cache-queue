"""
In-memory rate limiter for the Genie API (5 QPM per workspace).
Single-replica, no persistence needed — limits reset on restart.
"""

import logging
import threading
from datetime import datetime
from typing import Optional, List

logger = logging.getLogger(__name__)


class RateLimiterService:
    """
    In-memory rate limiting service.
    Uses a sliding window to enforce Genie API QPM limits.
    """

    def __init__(self):
        self.rate_limits = {}
        self.query_status = {}
        self._rate_lock = threading.Lock()

    def check_rate_limit(self, identity: str, max_per_minute: int = 5) -> bool:
        """Check if the Genie API rate limit has been exceeded (thread-safe).
        Uses a global sliding window of 60 seconds shared across all identities.
        """
        global_key = "__workspace__"
        with self._rate_lock:
            now = datetime.now()

            if global_key in self.rate_limits:
                self.rate_limits[global_key] = [
                    (ts, count) for ts, count in self.rate_limits[global_key]
                    if (now - ts).total_seconds() < 60
                ]

            if global_key not in self.rate_limits:
                self.rate_limits[global_key] = []

            current_count = sum(count for _, count in self.rate_limits[global_key])

            logger.info("Rate limit check: count=%d/%d identity=%s", current_count, max_per_minute, identity)

            if current_count >= max_per_minute:
                logger.warning("Rate limit exceeded: %d/%d identity=%s", current_count, max_per_minute, identity)
                return False

            self.rate_limits[global_key].append((now, 1))
            return True

    def save_query_status(self, query_id: str, status_data: dict):
        """Save query status information"""
        self.query_status[query_id] = status_data

    def get_query_status(self, query_id: str) -> Optional[dict]:
        """Get query status information"""
        return self.query_status.get(query_id)

    def update_query_stage(self, query_id: str, stage: str, **kwargs):
        """Update the stage of a query"""
        if query_id in self.query_status:
            self.query_status[query_id]['stage'] = stage
            self.query_status[query_id]['updated_at'] = datetime.now().isoformat()
            self.query_status[query_id].update(kwargs)


_rate_limiter = None


def get_rate_limiter() -> RateLimiterService:
    """Get or create rate limiter instance"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiterService()
    return _rate_limiter
