"""
Local storage backend for development/testing without Docker.
Uses JSON files and numpy arrays for lightweight operation.
"""

import logging
import json
import threading
import numpy as np
from typing import Optional, List, Tuple, Dict
from datetime import datetime, timedelta
import os
from pathlib import Path
try:
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError:
    cosine_similarity = None

logger = logging.getLogger(__name__)


class LocalStorageService:
    """
    Lightweight storage service for local development.
    Replaces PostgreSQL/pgvector with file-based storage.
    """

    def __init__(self, cache_file: str, embeddings_file: str, cache_ttl_hours: int = 24):
        self.cache_file = cache_file
        self.embeddings_file = embeddings_file
        self.cache_ttl_hours = cache_ttl_hours
        self._ensure_data_dir()
        self._load_data()

    def _ensure_data_dir(self):
        """Ensure data directory exists"""
        Path(self.cache_file).parent.mkdir(parents=True, exist_ok=True)

    def _load_data(self):
        """Load cache and embeddings from disk"""
        if os.path.exists(self.cache_file):
            with open(self.cache_file, 'r') as f:
                self.cache = json.load(f)
        else:
            self.cache = []

        if os.path.exists(self.embeddings_file):
            self.embeddings = np.load(self.embeddings_file)
        else:
            self.embeddings = np.array([]).reshape(0, 0)

    def _save_data(self):
        """Save cache and embeddings to disk"""
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f, indent=2, default=str)

        np.save(self.embeddings_file, self.embeddings)

    def search_similar_query(
        self,
        query_embedding: List[float],
        identity: str,
        threshold: float = 0.92,
        cache_ttl_hours: float = None,
        shared_cache: bool = True
    ) -> Optional[Tuple[int, str, str, float]]:
        """Search for similar cached queries using cosine similarity.
        Only matches entries within the freshness window (cache_ttl_hours).
        If shared_cache=True, searches all entries regardless of identity.
        If shared_cache=False, filters by identity.
        """
        if len(self.cache) == 0:
            return None

        ttl = cache_ttl_hours if cache_ttl_hours is not None else self.cache_ttl_hours

        # Filter by freshness window (and optionally by identity)
        now = datetime.now()
        matches = []
        for idx, item in enumerate(self.cache):
            if not shared_cache and item['identity'] != identity:
                continue
            # Apply freshness window (0 = no limit)
            if ttl and ttl > 0:
                created = datetime.fromisoformat(item.get('created_at', '2000-01-01'))
                if (now - created) > timedelta(hours=ttl):
                    continue
            matches.append((idx, item))

        if not matches:
            return None

        # Get embeddings for matches
        indices = [idx for idx, _ in matches]
        matched_embeddings = self.embeddings[indices]

        # Calculate cosine similarity
        query_emb = np.array(query_embedding).reshape(1, -1)
        if cosine_similarity is not None:
            similarities = cosine_similarity(query_emb, matched_embeddings)[0]
        else:
            # Fallback: manual cosine similarity using numpy
            norms_q = np.linalg.norm(query_emb, axis=1, keepdims=True)
            norms_m = np.linalg.norm(matched_embeddings, axis=1, keepdims=True)
            similarities = (query_emb @ matched_embeddings.T / (norms_q * norms_m.T + 1e-10))[0]

        # Find best match
        best_idx = np.argmax(similarities)
        best_similarity = similarities[best_idx]

        if best_similarity >= threshold:
            cache_idx = indices[best_idx]
            item = self.cache[cache_idx]

            item['last_used'] = datetime.now().isoformat()
            item['use_count'] = item.get('use_count', 0) + 1
            self._save_data()

            return (
                item['id'],
                item['query_text'],
                item['sql_query'],
                float(best_similarity)
            )

        return None

    def save_query_cache(
        self,
        query_text: str,
        query_embedding: List[float],
        sql_query: str,
        identity: str,
        genie_space_id: str
    ) -> int:
        """Save a new query to the cache"""
        new_id = max([item.get('id', 0) for item in self.cache], default=0) + 1

        new_item = {
            'id': new_id,
            'query_text': query_text,
            'sql_query': sql_query,
            'identity': identity,
            'genie_space_id': genie_space_id,
            'created_at': datetime.now().isoformat(),
            'last_used': datetime.now().isoformat(),
            'use_count': 1
        }

        self.cache.append(new_item)

        embedding_array = np.array(query_embedding).reshape(1, -1)
        new_dim = embedding_array.shape[1]

        if self.embeddings.size == 0:
            self.embeddings = embedding_array
        elif self.embeddings.shape[1] != new_dim:
            logger.warning("Embedding dimension mismatch: cached=%d new=%d, clearing cache",
                           self.embeddings.shape[1], new_dim)
            self.cache = []
            self.embeddings = embedding_array
        else:
            self.embeddings = np.vstack([self.embeddings, embedding_array])

        self._save_data()
        return new_id

    def get_all_cached_queries(self, identity: Optional[str] = None) -> List[Dict]:
        """Get all cached queries (no TTL filtering - shows full history)."""
        if identity:
            return [item for item in self.cache if item['identity'] == identity]
        return self.cache


class LocalQueueService:
    """
    In-memory queue and rate limiting service for local development.
    Replaces Redis.
    """

    def __init__(self):
        self.queue = []
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

    def add_to_queue(self, query_id: str, query_data: dict) -> int:
        """Add a query to the processing queue"""
        query_data['queued_at'] = datetime.now().isoformat()
        self.queue.append({
            'query_id': query_id,
            **query_data
        })
        return len(self.queue)

    def get_from_queue(self) -> Optional[dict]:
        """Get the next query from the queue"""
        if self.queue:
            return self.queue.pop(0)
        return None

    def get_queue_length(self) -> int:
        """Get the current queue length"""
        return len(self.queue)

    def get_all_queued(self) -> List[dict]:
        """Get all queued queries without removing them"""
        return self.queue.copy()

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


_local_storage = None
_local_queue = None


def get_local_storage(cache_file: str, embeddings_file: str, cache_ttl_hours: int = 24) -> LocalStorageService:
    """Get or create local storage instance"""
    global _local_storage
    if _local_storage is None:
        _local_storage = LocalStorageService(cache_file, embeddings_file, cache_ttl_hours)
    return _local_storage


def get_local_queue() -> LocalQueueService:
    """Get or create local queue instance"""
    global _local_queue
    if _local_queue is None:
        _local_queue = LocalQueueService()
    return _local_queue
