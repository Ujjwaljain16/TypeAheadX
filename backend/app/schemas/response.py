from __future__ import annotations

from pydantic import BaseModel, Field


class SuggestionItem(BaseModel):
    query: str
    historical_count: int


class SuggestionResponse(BaseModel):
    prefix: str
    total_results: int = Field(ge=0)
    suggestions: list[SuggestionItem]
