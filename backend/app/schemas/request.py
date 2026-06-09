from __future__ import annotations

from pydantic import BaseModel, Field


class SuggestionRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=64)
