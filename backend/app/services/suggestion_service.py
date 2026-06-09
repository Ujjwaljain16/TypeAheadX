from __future__ import annotations

from ..repositories.query_repository import QueryRepository
from ..schemas.response import SuggestionItem, SuggestionResponse
from ..cache.base import CacheInterface


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

    def suggest(self, prefix: str, *, limit: int | None = None) -> SuggestionResponse:
        normalized_prefix = self._normalize_prefix(prefix)
        effective_limit = self._default_limit if limit is None else limit
        
        # 1. Check Cache
        cache_key = f"suggestion:{normalized_prefix}"
        cached_data = self._cache.get(cache_key)
        
        if cached_data is not None:
            # Cache HIT
            return SuggestionResponse(
                prefix=normalized_prefix,
                total_results=len(cached_data),
                suggestions=[SuggestionItem(**item) for item in cached_data]
            )
            
        # 2. Cache MISS / ERROR: Fallback to DB
        suggestions = self._repository.fetch_suggestions(normalized_prefix, effective_limit)
        
        # Prepare response
        response_items = [
            SuggestionItem(query=item.query, historical_count=item.historical_count) 
            for item in suggestions
        ]
        
        # 3. Store in Cache (Serialize to dicts for JSON)
        cache_value = [item.model_dump() for item in response_items]
        self._cache.set(cache_key, cache_value, self._cache_ttl_seconds)

        return SuggestionResponse(
            prefix=normalized_prefix,
            total_results=len(response_items),
            suggestions=response_items,
        )

    def validate_and_normalize(self, raw_prefix: str) -> str:
        normalized_prefix = self._normalize_prefix(raw_prefix)
        if not normalized_prefix:
            raise ValueError("q is required")
        if len(normalized_prefix) > self._max_prefix_length:
            raise ValueError("q is too long")
        return normalized_prefix

    def _normalize_prefix(self, raw_prefix: str) -> str:
        return " ".join(raw_prefix.strip().lower().split())
