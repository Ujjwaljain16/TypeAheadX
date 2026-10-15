import threading


class CacheMetrics:
    """
    Singleton for tracking cache performance and errors (per process; thread-safe).
    """
    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    errors: int = 0
    breaker_skips: int = 0      # operations short-circuited because the node's breaker was open
    node_hits: dict = {}
    _lock = threading.Lock()

    @classmethod
    def record_node_hit(cls, node_name: str):
        with cls._lock:
            cls.node_hits[node_name] = cls.node_hits.get(node_name, 0) + 1

    @classmethod
    def record_hit(cls):
        with cls._lock:
            cls.hits += 1

    @classmethod
    def record_miss(cls):
        with cls._lock:
            cls.misses += 1

    @classmethod
    def record_set(cls):
        with cls._lock:
            cls.sets += 1

    @classmethod
    def record_delete(cls, n: int = 1):
        with cls._lock:
            cls.deletes += n

    @classmethod
    def record_error(cls):
        with cls._lock:
            cls.errors += 1

    @classmethod
    def record_skip(cls):
        with cls._lock:
            cls.breaker_skips += 1

    @classmethod
    def get_hit_rate(cls) -> float:
        total = cls.hits + cls.misses
        if total == 0:
            return 0.0
        return round((cls.hits / total) * 100, 2)

    @classmethod
    def get_metrics(cls) -> dict:
        return {
            "hits": cls.hits,
            "misses": cls.misses,
            "sets": cls.sets,
            "deletes": cls.deletes,
            "errors": cls.errors,
            "breaker_skips": cls.breaker_skips,
            "hit_rate": cls.get_hit_rate(),
            "node_hits": dict(cls.node_hits)
        }

    @classmethod
    def reset(cls):
        with cls._lock:
            cls.hits = 0
            cls.misses = 0
            cls.sets = 0
            cls.deletes = 0
            cls.errors = 0
            cls.breaker_skips = 0
            cls.node_hits = {}
