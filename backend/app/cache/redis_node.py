import logging
import time

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from ..utils.breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class RedisNode:
    """One Redis endpoint plus a small circuit breaker.

    Why: with blocking sync I/O in a bounded thread pool, every request routed to a dead node used to
    hold a worker thread for the full socket timeout (get, then set). A single failed node therefore
    starved the pool and took the *whole* API down. After a failure the node is now "open" (skipped,
    i.e. a cache miss, no network I/O) for ``breaker_seconds``; then exactly one request probes it
    (half-open) while the others keep skipping.
    """

    def __init__(self, name: str, host: str, port: int, timeout: float = 0.25,
                 breaker_seconds: float = 5.0, clock=time.monotonic):
        self.name = name
        self.host = host
        self.port = port
        self.breaker_seconds = breaker_seconds
        self._breaker = CircuitBreaker(breaker_seconds, clock)
        # redis-py connects lazily, so constructing the client never fails and a node that is down at
        # start-up is picked up automatically once it comes back (previously client=None forever).
        self.client = redis.Redis(
            host=host,
            port=port,
            decode_responses=True,
            socket_timeout=timeout,
            socket_connect_timeout=timeout,
            max_connections=50,
            # redis-py >= 6 retries failed commands 3x with exponential backoff by default: a 250 ms
            # timeout then costs 5-8 s per call (measured), which re-creates the thread-pool starvation
            # the breaker exists to prevent. Failures are handled by the breaker, not by retrying.
            retry=Retry(NoBackoff(), 0),
        )
        try:
            self.client.ping()
            logger.info(f"Connected to Redis node {name} at {host}:{port}")
        except Exception as e:
            logger.error(f"Redis node {name} at {host}:{port} not reachable at start-up: {e}")
            self._trip()

    # -- breaker (see utils/breaker.py) --------------------------------------------------------
    def _trip(self) -> None:
        self._breaker.record_failure()

    def allow(self) -> bool:
        """True if a request may use this node (closed, or this caller is the half-open probe)."""
        return self._breaker.allow()

    def record_success(self) -> None:
        if self._breaker.record_success():
            logger.info(f"Redis node {self.name} recovered")

    def record_failure(self) -> None:
        self._breaker.record_failure()

    @property
    def is_open(self) -> bool:
        return self._breaker.is_open
