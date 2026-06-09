import threading
from typing import Dict

class WriteBuffer:
    def __init__(self):
        self._buffer: Dict[str, int] = {}
        self._lock = threading.Lock()

    def increment(self, query: str) -> None:
        """
        Thread-safe increment of a query in the buffer.
        """
        with self._lock:
            self._buffer[query] = self._buffer.get(query, 0) + 1

    def flush(self) -> Dict[str, int]:
        """
        Thread-safe copy-on-clear flush.
        Returns the snapshot of the buffer and clears the original.
        """
        with self._lock:
            snapshot = dict(self._buffer)
            self._buffer.clear()
            return snapshot

    def get_size(self) -> int:
        """
        Returns the number of unique queries in the buffer.
        """
        with self._lock:
            return len(self._buffer)

# Singleton instance
write_buffer = WriteBuffer()
