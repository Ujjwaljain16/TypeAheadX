from __future__ import annotations

from ..repositories.query_repository import QueryRepository
from ..schemas.response import SuggestionItem, SuggestionResponse


class SuggestionService:
    def __init__(self, repository: QueryRepository, *, max_prefix_length: int, default_limit: int):
        self._repository = repository
        self._max_prefix_length = max_prefix_length
        self._default_limit = default_limit

    def suggest(self, prefix: str, *, limit: int | None = None) -> SuggestionResponse:
        normalized_prefix = self._normalize_prefix(prefix)
        effective_limit = self._default_limit if limit is None else limit
        suggestions = self._repository.fetch_suggestions(normalized_prefix, effective_limit)
        return SuggestionResponse(
            prefix=normalized_prefix,
            total_results=len(suggestions),
            suggestions=[SuggestionItem(query=item.query, historical_count=item.historical_count) for item in suggestions],
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
