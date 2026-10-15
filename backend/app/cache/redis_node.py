import logging
import random
import threading
import time

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

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
        self._clock = clock
        self._lock = threading.Lock()
        self._open_until = 0.0
        self._probing = False
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

    # -- breaker -----------------------------------------------------------------------------
    def _trip(self) -> None:
        with self._lock:
            jitter = 1.0 + random.random() * 0.2  # nosec B311          # de-synchronise probes of different processes
            self._open_until = self._clock() + self.breaker_seconds * jitter
            self._probing = False

    def allow(self) -> bool:
        """True if a request may use this node (closed, or this caller is the half-open probe)."""
        with self._lock:
            if self._open_until == 0.0:
                return True
            if self._clock() < self._open_until or self._probing:
                return False
            self._probing = True
            return True

    def record_success(self) -> None:
        if self._open_until or self._probing:
            with self._lock:
                self._open_until = 0.0
                self._probing = False
            logger.info(f"Redis node {self.name} recovered")

    def record_failure(self) -> None:
        self._trip()

    @property
    def is_open(self) -> bool:
        return self._open_until != 0.0 and self._clock() < self._open_until
