import random
import threading
import time


class CircuitBreaker:
    """Minimal thread-safe circuit breaker with a single half-open probe.

    * closed: ``allow()`` is True.
    * ``record_failure()`` opens it for ``open_seconds`` (+0..20 % jitter so that several processes do not
      probe a recovering dependency in lock-step). While open, ``allow()`` is False and callers must skip the
      dependency entirely (no network I/O).
    * when the window has elapsed exactly ONE caller gets ``allow() == True`` (the probe); everybody else keeps
      being refused until the probe reports ``record_success()`` (closes) or ``record_failure()`` (re-opens).
      A caller that is granted ``allow()`` MUST report one of the two.
    """

    def __init__(self, open_seconds: float, clock=time.monotonic):
        self.open_seconds = open_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._open_until = 0.0
        self._probing = False

    def allow(self) -> bool:
        with self._lock:
            if self._open_until == 0.0:
                return True
            if self._clock() < self._open_until or self._probing:
                return False
            self._probing = True
            return True

    def record_success(self) -> bool:
        """Close the breaker. Returns True if it was open (i.e. this is a recovery)."""
        if self._open_until or self._probing:
            with self._lock:
                was_open = self._open_until != 0.0
                self._open_until = 0.0
                self._probing = False
            return was_open
        return False

    def cancel_probe(self) -> None:
        """The caller that was granted ``allow()`` never reached the dependency: let somebody else probe.
        Does not change the open/closed state."""
        with self._lock:
            self._probing = False

    def record_failure(self) -> None:
        with self._lock:
            jitter = 1.0 + random.random() * 0.2  # nosec B311 - de-synchronisation, not security
            self._open_until = self._clock() + self.open_seconds * jitter
            self._probing = False

    @property
    def is_open(self) -> bool:
        return self._open_until != 0.0 and self._clock() < self._open_until
