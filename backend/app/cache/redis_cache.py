import logging
from urllib.parse import urlparse

from app.database.config import get_settings
from .distributed_cache import DistributedCache
from .consistent_hash_ring import ConsistentHashRing

logger = logging.getLogger(__name__)


class RedisCache(DistributedCache):
    """Single-Redis provider (CACHE_PROVIDER=redis): a one-node ring that shares the timeout,
    circuit-breaker and lazy-reconnect behaviour of DistributedCache instead of duplicating it."""

    def __init__(self):
        settings = get_settings()
        self._timeout = settings.redis_timeout_seconds
        self._breaker_seconds = settings.redis_breaker_seconds
        self.ring = ConsistentHashRing(virtual_nodes=1)
        self.nodes = {}
        u = urlparse(settings.redis_url)
        self._add_node("redis", u.hostname or "localhost", u.port or 6379)
