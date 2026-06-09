from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuerySuggestion:
    query: str
    historical_count: int
