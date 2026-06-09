from dataclasses import dataclass
import threading

@dataclass
class WriteMetricsData:
    searches_received: int = 0
    flushes_executed: int = 0
    db_writes_executed: int = 0
    db_writes_avoided: int = 0
    
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

    def record_flush(self, db_writes_executed: int, db_writes_avoided: int):
        with self._lock:
            self.data.flushes_executed += 1
            self.data.db_writes_executed += db_writes_executed
            self.data.db_writes_avoided += db_writes_avoided

    def get_snapshot(self) -> WriteMetricsData:
        with self._lock:
            # Return a copy to avoid threading issues
            return WriteMetricsData(
                searches_received=self.data.searches_received,
                flushes_executed=self.data.flushes_executed,
                db_writes_executed=self.data.db_writes_executed,
                db_writes_avoided=self.data.db_writes_avoided
            )

# Singleton instance
write_metrics = WriteMetrics()
