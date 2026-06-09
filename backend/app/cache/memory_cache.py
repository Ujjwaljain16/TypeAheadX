import time
import logging
from typing import Optional, Any, Dict, Tuple
from .base import CacheInterface
from .metrics import CacheMetrics

logger = logging.getLogger(__name__)

class InMemoryCache(CacheInterface):
    def __init__(self):
        # Store as {key: (value, expire_at)}
        self._store: Dict[str, Tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        try:
            if key in self._store:
                value, expire_at = self._store[key]
                if time.time() > expire_at:
                    # Expired
                    del self._store[key]
                    CacheMetrics.record_miss()
                    return None
                CacheMetrics.record_hit()
                return value
            
            CacheMetrics.record_miss()
            return None
        except Exception as e:
            logger.error(f"InMemoryCache error on get: {e}")
            CacheMetrics.record_error()
            return None

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        try:
            expire_at = time.time() + ttl_seconds
            self._store[key] = (value, expire_at)
            CacheMetrics.record_set()
        except Exception as e:
            logger.error(f"InMemoryCache error on set: {e}")
            CacheMetrics.record_error()

    def delete(self, key: str) -> None:
        try:
            if key in self._store:
                del self._store[key]
                CacheMetrics.record_delete()
        except Exception as e:
            logger.error(f"InMemoryCache error on delete: {e}")
            CacheMetrics.record_error()

    def get_ttl(self, key: str) -> int:
        if key in self._store:
            _, expire_at = self._store[key]
            remaining = int(expire_at - time.time())
            return max(0, remaining)
        return -2 # Key not found
