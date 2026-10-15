import time
import threading
import logging
from typing import Dict, Optional, Set

from .buffer import write_buffer, WriteBuffer
from .metrics import write_metrics, WriteMetrics
from ..repositories.query_repository import QueryRepository
from ..database.session import get_session
from ..database.config import get_settings, Settings
from ..services.normalization import suggestion_cache_key

logger = logging.getLogger(__name__)


class BatchWorker:
    """Flushes the in-memory write buffer to PostgreSQL.

    Durability model (unchanged in spirit): buffered events live only in this process's memory
    until a flush commits, so a crash (SIGKILL/OOM/power loss) loses up to one flush window of
    events. What *is* guaranteed:
      * a failed DB write never discards events - they are put back into the buffer (bounded);
      * a single bad row cannot take the rest of the batch down (it is isolated and dropped);
      * a graceful shutdown performs a final flush;
      * a commit is never followed by a re-queue of the same events (no double counting).
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        repository: Optional[QueryRepository] = None,
        cache=None,
        buffer: WriteBuffer = write_buffer,
        metrics: WriteMetrics = write_metrics,
    ):
        self.settings = settings or get_settings()
        self.repository = repository or QueryRepository(session_factory=get_session)
        self._cache = cache
        self.buffer = buffer
        self.metrics = metrics
        self._stop_event = threading.Event()
        self._thread = None
        self.last_flush_time = time.time()

    @property
    def cache(self):
        # resolved lazily: importing this module must not open network connections
        if self._cache is None:
            from ..cache.factory import CacheFactory
            self._cache = CacheFactory.get_cache()
        return self._cache

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="batch-worker")
            self._thread.start()
            logger.info("Batch worker started.")

    def stop(self):
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=30)
            logger.info("Batch worker stopped.")
        # Final flush on shutdown - also when the loop thread had died.
        self.flush()

    def _run_loop(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(1.0)  # wakes immediately on stop()
            if self._stop_event.is_set():
                break
            try:
                now = time.time()
                time_elapsed = now - self.last_flush_time
                buffer_size = self.buffer.get_size()

                should_flush = (
                    time_elapsed >= self.settings.write_buffer_flush_interval_seconds or
                    buffer_size >= self.settings.write_buffer_size
                )

                if should_flush and buffer_size > 0:
                    self.flush()
                    self.last_flush_time = time.time()
            except Exception:  # the loop must survive anything, or buffered writes silently stop
                logger.exception("Unexpected error in batch worker loop")

    # ------------------------------------------------------------------ flush
    def flush(self):
        snapshot = self.buffer.flush()
        if not snapshot:
            return

        started = time.perf_counter()
        written, dropped_rows, pending = self._write(snapshot)

        if pending:
            # Transient failure (database unreachable, pool timeout ...): these rows were NOT committed.
            lost = self.buffer.merge(pending)
            self.metrics.record_flush_failure(requeued=sum(pending.values()) - lost, dropped=lost)
            logger.error("Flush failed for %d queries; re-queued", len(pending))

        if not written and not dropped_rows:
            return

        # ---- committed rows: nothing below may re-queue events (that would double count them)
        dropped_events = sum(snapshot[q] for q in dropped_rows)
        if dropped_events:
            self.metrics.record_dropped(dropped_events)
        try:
            self._invalidate_cache(list(written))
        except Exception:
            logger.exception("Cache invalidation after flush failed (entries expire by TTL)")

        if written:
            total_deltas = sum(written.values())
            self.metrics.record_flush(
                db_writes_executed=len(written),
                db_writes_avoided=max(0, total_deltas - len(written)),
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
            logger.info("Flushed %d queries to DB. Avoided %d writes.", len(written), max(0, total_deltas - len(written)))

    def _write(self, snapshot: Dict[str, int]):
        """Persist ``snapshot``; returns ``(written, dropped_query_names, pending)``.

        * ``written``  - rows committed.
        * ``dropped``  - rows that the (reachable) database rejects even on their own; discarded.
        * ``pending``  - rows NOT committed because the database is unreachable; caller re-queues them.

        If a batch fails while the database is reachable the cause is data-related, so the batch is
        bisected to isolate the offending row(s) and everything else is still persisted.
        """
        lam = self.settings.trending_lambda
        try:
            self.repository.apply_search_counts(snapshot, lam)
            return dict(snapshot), [], {}
        except Exception:
            logger.warning("Batch of %d failed; checking database reachability", len(snapshot), exc_info=True)
            try:
                self.repository.ping()
            except Exception:
                return {}, [], dict(snapshot)  # database down/unreachable -> transient
            if len(snapshot) == 1:
                (query,) = snapshot
                logger.error("Dropping unpersistable query (len=%d): %r", len(query), query[:40])
                return {}, [query], {}
            items = sorted(snapshot.items())
            mid = len(items) // 2
            written: Dict[str, int] = {}
            dropped: list = []
            pending: Dict[str, int] = {}
            for half in (dict(items[:mid]), dict(items[mid:])):
                w, d, p = self._write(half)
                written.update(w)
                dropped.extend(d)
                pending.update(p)
            return written, dropped, pending

    # ----------------------------------------------------------- invalidation
    def _invalidate_cache(self, queries: list[str]):
        """
        Deduplicates all prefixes for the updated queries and invalidates their cache keys.
        The keys MUST be built exactly as the read path builds them (suggestion_cache_key);
        a previous version used a different prefix ("suggest:") so nothing was ever invalidated.
        """
        prefixes: Set[str] = set()

        for query in queries:
            # Generate all prefixes for this query up to max length
            for i in range(1, min(len(query), self.settings.max_prefix_length) + 1):
                prefixes.add(query[:i])

        self.cache.delete_many([suggestion_cache_key(prefix) for prefix in prefixes])


# Singleton instance
batch_worker = BatchWorker()
