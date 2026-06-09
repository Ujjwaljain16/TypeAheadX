import time
import threading
import logging
from typing import Set

from .buffer import write_buffer
from .metrics import write_metrics
from ..services.trending_calculator import TrendingCalculator
from ..repositories.query_repository import QueryRepository
from ..database.session import get_session
from ..database.config import get_settings
from ..cache.factory import CacheFactory

logger = logging.getLogger(__name__)

class BatchWorker:
    def __init__(self):
        self.settings = get_settings()
        self.calculator = TrendingCalculator(decay_lambda=self.settings.trending_lambda)
        self.repository = QueryRepository(session_factory=get_session)
        self.cache = CacheFactory.get_cache()
        self._stop_event = threading.Event()
        self._thread = None
        self.last_flush_time = time.time()

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            logger.info("Batch worker started.")

    def stop(self):
        if self._thread is not None and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join()
            logger.info("Batch worker stopped.")
            
            # Final flush on shutdown
            self.flush()

    def _run_loop(self):
        while not self._stop_event.is_set():
            time.sleep(1) # Sleep in small increments to allow quick shutdown
            
            now = time.time()
            time_elapsed = now - self.last_flush_time
            buffer_size = write_buffer.get_size()
            
            should_flush = (
                time_elapsed >= self.settings.write_buffer_flush_interval_seconds or
                buffer_size >= self.settings.write_buffer_size
            )
            
            if should_flush and buffer_size > 0:
                self.flush()
                self.last_flush_time = time.time()

    def flush(self):
        snapshot = write_buffer.flush()
        if not snapshot:
            return
            
        queries = list(snapshot.keys())
        
        try:
            # 1. Get current state from DB
            db_rows = self.repository.get_queries_by_names(queries)
            
            # 2. Compute exponential decay and new values
            updates = self.calculator.compute_decayed_updates(snapshot, db_rows)
            
            # 3. Upsert to DB
            self.repository.upsert_batch_with_trending(updates)
            
            # 4. Active Prefix Invalidation (Deduplicated)
            self._invalidate_cache(queries)
            
            # 5. Record Metrics
            writes_executed = len(updates)
            total_deltas = sum(snapshot.values())
            writes_avoided = total_deltas - writes_executed
            
            write_metrics.record_flush(
                db_writes_executed=writes_executed,
                db_writes_avoided=max(0, writes_avoided)
            )
            
            logger.info(f"Flushed {writes_executed} queries to DB. Avoided {writes_avoided} writes.")
            
        except Exception as e:
            logger.error(f"Failed to flush batch buffer: {e}")
            # If we fail, the snapshot is lost since we used copy-on-clear.
            # This is the accepted ephemeral data loss trade-off.

    def _invalidate_cache(self, queries: list[str]):
        """
        Deduplicates all prefixes for the updated queries and invalidates their cache keys.
        """
        prefixes: Set[str] = set()
        
        for query in queries:
            query = query.strip()
            # Generate all prefixes for this query up to max length
            for i in range(1, min(len(query), self.settings.max_prefix_length) + 1):
                prefixes.add(query[:i])
                
        # Delete from distributed cache
        for prefix in prefixes:
            cache_key = f"suggest:{prefix}"
            self.cache.delete(cache_key)

# Singleton instance
batch_worker = BatchWorker()
