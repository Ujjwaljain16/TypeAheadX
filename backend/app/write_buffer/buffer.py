import threading
from typing import Dict, Mapping


class WriteBuffer:
    """Thread-safe in-memory aggregation of search counts (query -> count).

    The number of *distinct* queries is bounded (``max_unique``): without a bound,
    an unauthenticated client posting unique strings grows memory without limit.
    Counts for queries already in the buffer are always accepted.
    """

    def __init__(self, max_unique: int = 50_000):
        self._buffer: Dict[str, int] = {}
        self._lock = threading.Lock()
        self.max_unique = max_unique

    def increment(self, query: str) -> bool:
        """Thread-safe increment. Returns False if the event was dropped because the buffer is full."""
        with self._lock:
            if query not in self._buffer and len(self._buffer) >= self.max_unique:
                return False
            self._buffer[query] = self._buffer.get(query, 0) + 1
            return True

    def flush(self) -> Dict[str, int]:
        """
        Thread-safe copy-on-clear flush.
        Returns the snapshot of the buffer and clears the original.
        """
        with self._lock:
            snapshot = dict(self._buffer)
            self._buffer.clear()
            return snapshot

    def merge(self, snapshot: Mapping[str, int]) -> int:
        """Put a previously flushed snapshot back (after a failed DB write).

        Returns the number of *events* that could not be restored because the
        buffer reached ``max_unique`` in the meantime.
        """
        lost = 0
        with self._lock:
            for query, n in snapshot.items():
                if query not in self._buffer and len(self._buffer) >= self.max_unique:
                    lost += n
                    continue
                self._buffer[query] = self._buffer.get(query, 0) + n
        return lost

    def get_size(self) -> int:
        """
        Returns the number of unique queries in the buffer.
        """
        with self._lock:
            return len(self._buffer)

    def total_events(self) -> int:
        with self._lock:
            return sum(self._buffer.values())


# Singleton instance (bound is applied from settings at application start-up)
write_buffer = WriteBuffer()
