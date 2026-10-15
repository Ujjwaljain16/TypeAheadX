"""Deadline + bulkhead + circuit breaker for READ-path database calls.

Problem (finding F-27): sync SQLAlchemy/psycopg calls cannot be interrupted client-side. If PostgreSQL stops
answering without closing the connection (frozen process, black-holed network, stuck failover) the kernel keeps
ACKing, so no TCP timeout ever fires and every request that needs the database holds one of the 40 request
threads indefinitely. After 40 such requests the whole API - including requests that could be answered from the
cache - is unresponsive.

What this does for calls routed through ``DatabaseGuard.call``:
  * the call runs on a small pool of daemon worker threads and the request thread waits at most ``timeout_s``;
  * at most ``max_concurrency`` calls are in flight; further callers are rejected immediately (bulkhead) instead of
    queueing behind hung ones, so hung workers can never consume the request threads;
  * the first timeout / connection-level error opens a circuit breaker for a few seconds - misses fail instantly
    with ``DatabaseUnavailable`` (HTTP 503) without touching the database, cache hits are unaffected - and a single
    probe call then tests recovery.

Deliberately NOT used for writes: when a write times out the statement may still be executed later, so retrying or
re-queueing it would double count. The background flush keeps its blocking, at-most-once behaviour and the bounded
write buffer protects memory meanwhile.

A worker thread stuck in a hung call stays stuck until the database answers or the connection is torn down; it holds
one bulkhead slot meanwhile (bounded: ``max_concurrency`` threads, all daemon so they cannot block process exit).
"""
from __future__ import annotations

import logging
import queue
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeout
from typing import Any, Callable

from sqlalchemy.exc import InterfaceError, OperationalError, TimeoutError as PoolTimeout

from ..utils.breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# errors that mean "the database (connection) is unhealthy" and should open the breaker; data/SQL errors do not
_TRIP_ON = (OperationalError, InterfaceError, PoolTimeout)


class DatabaseUnavailable(Exception):
    """The database did not answer in time, is saturated by hung calls, or the breaker is open (-> HTTP 503)."""


class DatabaseGuard:
    def __init__(self, max_concurrency: int = 15, timeout_s: float = 2.0, breaker_seconds: float = 5.0, clock=None):
        self.timeout_s = timeout_s
        self.max_concurrency = max_concurrency
        self._breaker = CircuitBreaker(breaker_seconds, **({"clock": clock} if clock else {}))
        self._slots = threading.BoundedSemaphore(max_concurrency)
        self._queue: "queue.SimpleQueue[Any]" = queue.SimpleQueue()
        self._workers = []
        self._start_lock = threading.Lock()
        self.timeouts = 0
        self.rejected_open = 0
        self.rejected_saturated = 0
        self._counter_lock = threading.Lock()

    # -- worker pool (daemon threads, started lazily) -------------------------------------------
    def _ensure_workers(self) -> None:
        if self._workers:
            return
        with self._start_lock:
            if self._workers:
                return
            for i in range(self.max_concurrency):
                t = threading.Thread(target=self._loop, name=f"db-guard-{i}", daemon=True)
                t.start()
                self._workers.append(t)

    def _loop(self) -> None:
        while True:
            fn, args, kwargs, fut = self._queue.get()
            try:
                if fut.set_running_or_notify_cancel():
                    try:
                        fut.set_result(fn(*args, **kwargs))
                    except BaseException as exc:  # noqa: BLE001 - delivered to the waiting caller
                        fut.set_exception(exc)
            finally:
                self._slots.release()   # the slot is held for as long as the call really runs, even after a timeout

    # -- public API -------------------------------------------------------------------------------
    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if not self._breaker.allow():
            with self._counter_lock:
                self.rejected_open += 1
            raise DatabaseUnavailable("database circuit open")
        if not self._slots.acquire(blocking=False):
            with self._counter_lock:
                self.rejected_saturated += 1
            self._breaker.cancel_probe()     # load, not a sick database: do not open the breaker, just free a probe grant
            raise DatabaseUnavailable("database calls saturated by hung requests")
        self._ensure_workers()
        fut: Future = Future()
        self._queue.put((fn, args, kwargs, fut))
        try:
            result = fut.result(timeout=self.timeout_s)
        except FutureTimeout:
            with self._counter_lock:
                self.timeouts += 1
            self._breaker.record_failure()
            logger.error("database call exceeded %.1fs; circuit opened", self.timeout_s)
            raise DatabaseUnavailable("database call timed out") from None
        except _TRIP_ON:
            self._breaker.record_failure()
            raise
        except BaseException:
            self._breaker.record_success()   # the database answered (SQL/data error): it is alive
            raise
        if self._breaker.record_success():
            logger.info("database recovered; circuit closed")
        return result

    @property
    def is_open(self) -> bool:
        return self._breaker.is_open

    def stats(self) -> dict:
        return {"breaker_open": self.is_open, "timeouts": self.timeouts, "rejected_breaker_open": self.rejected_open,
                "rejected_saturated": self.rejected_saturated, "max_concurrency": self.max_concurrency,
                "timeout_seconds": self.timeout_s}
