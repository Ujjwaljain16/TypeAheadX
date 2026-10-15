from __future__ import annotations

import threading
import time

from ..repositories.query_repository import QueryRepository
from ..schemas.response import SuggestionItem, SuggestionResponse
from ..cache.base import CacheInterface
from .normalization import normalize_text, suggestion_cache_key, validate_text

# Cached documents are the complete JSON response body, so a cache hit can be served without
# parsing/validating/re-serialising it. Entries that do not look like one are treated as misses.
_DOC_PREFIX = '{"prefix":'


class _Flight:
    """One in-progress miss computation that concurrent identical requests wait for."""
    __slots__ = ("event", "body")

    def __init__(self):
        self.event = threading.Event()
        self.body: str | None = None


class SuggestionService:
    def __init__(
        self, 
        repository: QueryRepository, 
        cache: CacheInterface,
        *, 
        max_prefix_length: int, 
        default_limit: int,
        cache_ttl_seconds: int
    ):
        self._repository = repository
        self._cache = cache
        self._max_prefix_length = max_prefix_length
        self._default_limit = default_limit
        self._cache_ttl_seconds = cache_ttl_seconds
        # Single-flight: concurrent misses for the same key share ONE database query (per process).
        self._flights: dict[str, _Flight] = {}
        self._flights_lock = threading.Lock()
        self._flight_timeout = 5.0
        # key -> monotonic time a flight for it last finished. Lets a new leader skip the "was it filled in the
        # meantime?" cache re-check (one extra Redis round trip) unless a flight for the key JUST completed.
        self._recent: dict[str, float] = {}

    def suggest_json(self, prefix: str, *, limit: int | None = None) -> str:
        """Cache-aside lookup returning the serialised SuggestionResponse (hot path)."""
        normalized_prefix = self._normalize_prefix(prefix)
        effective_limit = self._default_limit if limit is None else limit
        # The cache key does not encode the limit, so only default-limit results may use the cache.
        use_cache = effective_limit == self._default_limit

        # 1. Check Cache
        cache_key = suggestion_cache_key(normalized_prefix)
        if use_cache:
            cached = self._cache.get_raw(cache_key)
            if isinstance(cached, str) and cached.startswith(_DOC_PREFIX):
                return cached  # Cache HIT

        # 2. Cache MISS / ERROR (or malformed entry): fall back to the database
        if not use_cache:
            return self._load(cache_key, normalized_prefix, effective_limit, store=False)
        return self._single_flight(cache_key, normalized_prefix, effective_limit)

    def _load(self, cache_key: str, normalized_prefix: str, limit: int, *, store: bool) -> str:
        suggestions = self._repository.fetch_suggestions(normalized_prefix, limit)
        response = SuggestionResponse(
            prefix=normalized_prefix,
            total_results=len(suggestions),
            suggestions=[SuggestionItem(query=s.query, historical_count=s.historical_count) for s in suggestions],
        )
        body = response.model_dump_json()
        # 3. Store in Cache
        if store:
            self._cache.set_raw(cache_key, body, self._cache_ttl_seconds)
        return body

    def _single_flight(self, cache_key: str, normalized_prefix: str, limit: int) -> str:
        with self._flights_lock:
            flight = self._flights.get(cache_key)
            leader = flight is None
            if leader:
                flight = self._flights[cache_key] = _Flight()
        if leader:
            try:
                # Double-checked: a previous leader may have stored the result between our cache miss
                # and our becoming leader (its flight was already removed).
                cached = None
                finished = self._recent.get(cache_key)
                if finished is not None and time.monotonic() - finished < 1.0:
                    cached = self._cache.get_raw(cache_key)
                if isinstance(cached, str) and cached.startswith(_DOC_PREFIX):
                    flight.body = cached
                else:
                    flight.body = self._load(cache_key, normalized_prefix, limit, store=True)
                return flight.body
            finally:
                with self._flights_lock:
                    self._flights.pop(cache_key, None)
                    if len(self._recent) > 4096:      # bounded: forget everything rather than grow
                        self._recent.clear()
                    self._recent[cache_key] = time.monotonic()
                flight.event.set()   # on failure body stays None: followers fall back to their own query
        flight.event.wait(self._flight_timeout)
        if flight.body is not None:
            return flight.body
        return self._load(cache_key, normalized_prefix, limit, store=True)

    def suggest(self, prefix: str, *, limit: int | None = None) -> SuggestionResponse:
        return SuggestionResponse.model_validate_json(self.suggest_json(prefix, limit=limit))

    def validate_and_normalize(self, raw_prefix: str) -> str:
        return validate_text(raw_prefix, self._max_prefix_length, what="q")

    def _normalize_prefix(self, raw_prefix: str) -> str:
        return normalize_text(raw_prefix)
