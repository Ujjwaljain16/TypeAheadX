from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Iterator


@contextmanager
def timer() -> Iterator[callable[[], float]]:
    start = perf_counter()

    def elapsed_ms() -> float:
        return (perf_counter() - start) * 1000.0

    yield elapsed_ms
