import os
import json
import logging
import redis
from typing import Optional, Any
from .base import CacheInterface
from .metrics import CacheMetrics

logger = logging.getLogger(__name__)

class RedisCache(CacheInterface):
    def __init__(self):
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        try:
            # Create a robust connection pool. 
            # decode_responses=True means we get strings back instead of bytes
            self.client = redis.from_url(
                redis_url, 
                decode_responses=True,
                socket_timeout=1,      # Fast timeout to prevent blocking operations
                socket_connect_timeout=1
            )
            # Ping to verify immediately (optional, but good for fast failing)
            # We catch it below if it fails
            self.client.ping()
            logger.info(f"Connected to Redis at {redis_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis during init: {e}")
            # We don't crash, we just let subsequent operations fail gracefully
            self.client = None

    def get(self, key: str) -> Optional[Any]:
        if not self.client:
            CacheMetrics.record_error()
            return None

        try:
            result = self.client.get(key)
            if result:
                CacheMetrics.record_hit()
                return json.loads(result)
            CacheMetrics.record_miss()
            return None
        except Exception as e:
            logger.error(f"Redis get error for {key}: {e}")
            CacheMetrics.record_error()
            return None

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        if not self.client:
            CacheMetrics.record_error()
            return

        try:
            serialized = json.dumps(value)
            self.client.setex(key, ttl_seconds, serialized)
            CacheMetrics.record_set()
        except Exception as e:
            logger.error(f"Redis set error for {key}: {e}")
            CacheMetrics.record_error()

    def delete(self, key: str) -> None:
        if not self.client:
            CacheMetrics.record_error()
            return

        try:
            self.client.delete(key)
            CacheMetrics.record_delete()
        except Exception as e:
            logger.error(f"Redis delete error for {key}: {e}")
            CacheMetrics.record_error()

    def get_ttl(self, key: str) -> int:
        if not self.client:
            return -2
            
        try:
            return self.client.ttl(key)
        except Exception as e:
            logger.error(f"Redis ttl error for {key}: {e}")
            CacheMetrics.record_error()
            return -2
