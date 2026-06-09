class CacheMetrics:
    """
    Singleton for tracking cache performance and errors.
    """
    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    errors: int = 0

    @classmethod
    def record_hit(cls):
        cls.hits += 1

    @classmethod
    def record_miss(cls):
        cls.misses += 1

    @classmethod
    def record_set(cls):
        cls.sets += 1

    @classmethod
    def record_delete(cls):
        cls.deletes += 1

    @classmethod
    def record_error(cls):
        cls.errors += 1

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
            "hit_rate": cls.get_hit_rate()
        }

    @classmethod
    def reset(cls):
        cls.hits = 0
        cls.misses = 0
        cls.sets = 0
        cls.deletes = 0
        cls.errors = 0
