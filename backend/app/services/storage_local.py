"""
Local storage backend for development/testing without Docker.
Uses JSON files and numpy arrays for lightweight operation.
"""

import logging
import json
import os
import threading
from pathlib import Path
import numpy as np
from typing import Optional, List, Tuple, Dict
from datetime import datetime, timedelta, timezone
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
        self._gateways: Dict = {}
        self._roles_file = str(Path(cache_file).parent / "user_roles.json")
        self._ensure_data_dir()
        self._load_data()
        self._load_roles()

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
        genie_space_id: Optional[str] = None,
        cache_ttl_hours: float = None,
        shared_cache: bool = True
    ) -> Optional[Tuple[int, str, str, float]]:
        """Search for similar cached queries using cosine similarity.
        Only matches entries within the freshness window (cache_ttl_hours).
        If shared_cache=True, searches all entries regardless of identity.
        If shared_cache=False, filters by identity.
        Filters by genie_space_id when provided.
        """
        if len(self.cache) == 0:
            return None

        ttl = cache_ttl_hours if cache_ttl_hours is not None else self.cache_ttl_hours

        # Filter by freshness window, identity, and genie_space_id
        now = datetime.now()
        matches = []
        for idx, item in enumerate(self.cache):
            if not shared_cache and item['identity'] != identity:
                continue
            if genie_space_id and item.get('genie_space_id') != genie_space_id:
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
                float(best_similarity),
                item.get('original_query_text'),
            )

        return None

    def save_query_cache(
        self,
        query_text: str,
        query_embedding: List[float],
        sql_query: str,
        identity: str,
        gateway_id: str,
        original_query_text: str = None,
        genie_space_id: str = None,
    ) -> int:
        """Save a new query to the cache"""
        new_id = max([item.get('id', 0) for item in self.cache], default=0) + 1

        new_item = {
            'id': new_id,
            'query_text': query_text,
            'original_query_text': original_query_text,
            'sql_query': sql_query,
            'identity': identity,
            'gateway_id': gateway_id,
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

    def get_all_cached_queries(self, identity: Optional[str] = None, genie_space_id: Optional[str] = None) -> List[Dict]:
        """Get all cached queries (no TTL filtering - shows full history)."""
        results = self.cache
        if identity:
            results = [item for item in results if item['identity'] == identity]
        if genie_space_id:
            results = [item for item in results if item.get('genie_space_id') == genie_space_id]
        return results

    # --- Gateway CRUD ---

    def create_gateway(self, config: Dict) -> Dict:
        """Create a new gateway configuration."""
        gateway_id = config["id"]
        self._gateways[gateway_id] = config
        logger.info("Gateway created: id=%s name=%s", gateway_id, config.get("name"))
        return config

    def get_gateway(self, gateway_id: str) -> Optional[Dict]:
        """Get a gateway configuration by ID."""
        return self._gateways.get(gateway_id)

    def list_gateways(self) -> List[Dict]:
        """List all gateway configurations."""
        return list(self._gateways.values())

    def update_gateway(self, gateway_id: str, updates: Dict) -> Optional[Dict]:
        """Update a gateway configuration."""
        if gateway_id not in self._gateways:
            return None
        self._gateways[gateway_id].update(updates)
        self._gateways[gateway_id]["updated_at"] = datetime.now().isoformat()
        logger.info("Gateway updated: id=%s fields=%s", gateway_id, list(updates.keys()))
        return self._gateways[gateway_id]

    def delete_gateway(self, gateway_id: str) -> bool:
        """Delete a gateway configuration."""
        if gateway_id not in self._gateways:
            return False
        del self._gateways[gateway_id]
        logger.info("Gateway deleted: id=%s", gateway_id)
        return True

    # --- User roles CRUD (persisted to disk) ---

    def _load_roles(self):
        if os.path.exists(self._roles_file):
            with open(self._roles_file, 'r') as f:
                self._user_roles = json.load(f)
        else:
            self._user_roles = {}

    def _save_roles(self):
        with open(self._roles_file, 'w') as f:
            json.dump(self._user_roles, f, indent=2, default=str)

    def get_user_role(self, identity: str):
        entry = self._user_roles.get(identity)
        return entry["role"] if entry else None

    def set_user_role(self, identity: str, role: str, granted_by: str = None):
        self._user_roles[identity] = {
            "identity": identity,
            "role": role,
            "granted_by": granted_by,
            "granted_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_roles()

    def list_user_roles(self) -> list:
        return sorted(self._user_roles.values(), key=lambda r: r.get("granted_at", ""), reverse=True)

    def delete_user_role(self, identity: str):
        self._user_roles.pop(identity, None)
        self._save_roles()

    def count_owners(self) -> int:
        return sum(1 for r in self._user_roles.values() if r.get("role") == "owner")

    def get_gateway_stats(self, gateway_id: str) -> Dict:
        """Get cache and query stats for a gateway."""
        gw = self._gateways.get(gateway_id)
        if not gw:
            return {"cache_count": 0, "query_count_7d": 0}
        space_id = gw.get("genie_space_id")
        cache_count = sum(1 for item in self.cache if item.get("genie_space_id") == space_id)
        return {"cache_count": cache_count, "query_count_7d": 0}


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
