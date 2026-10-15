from dataclasses import dataclass
import threading

@dataclass
class WriteMetricsData:
    searches_received: int = 0
    flushes_executed: int = 0
    db_writes_executed: int = 0
    db_writes_avoided: int = 0
    # --- added for operability (additive; existing fields keep their meaning)
    flush_failures: int = 0          # flush attempts that raised before the DB commit
    events_requeued: int = 0         # events put back into the buffer after a failed flush
    events_dropped: int = 0          # events lost: buffer full on ingest, or on re-queue
    last_flush_duration_ms: float = 0.0
    max_flush_duration_ms: float = 0.0
    
    @property
    def write_reduction_percent(self) -> float:
        total_intended = self.db_writes_executed + self.db_writes_avoided
        if total_intended == 0:
            return 0.0
        return (self.db_writes_avoided / total_intended) * 100.0

class WriteMetrics:
    def __init__(self):
        self.data = WriteMetricsData()
        self._lock = threading.Lock()

    def record_search(self):
        with self._lock:
            self.data.searches_received += 1

    def record_flush(self, db_writes_executed: int, db_writes_avoided: int, duration_ms: float = 0.0):
        with self._lock:
            self.data.flushes_executed += 1
            self.data.db_writes_executed += db_writes_executed
            self.data.db_writes_avoided += db_writes_avoided
            self.data.last_flush_duration_ms = duration_ms
            self.data.max_flush_duration_ms = max(self.data.max_flush_duration_ms, duration_ms)

    def record_flush_failure(self, requeued: int, dropped: int):
        with self._lock:
            self.data.flush_failures += 1
            self.data.events_requeued += requeued
            self.data.events_dropped += dropped

    def record_dropped(self, n: int = 1):
        with self._lock:
            self.data.events_dropped += n

    def get_snapshot(self) -> WriteMetricsData:
        with self._lock:
            # Return a copy to avoid threading issues
            return WriteMetricsData(**vars(self.data))

# Singleton instance
write_metrics = WriteMetrics()
