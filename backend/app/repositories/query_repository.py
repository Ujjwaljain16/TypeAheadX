from __future__ import annotations

from typing import Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models.query import QuerySuggestion


class QueryRepository:
    def __init__(self, session_factory):
        """session_factory should be a context manager that yields a SQLAlchemy Session."""
        self._session_factory = session_factory

    def fetch_suggestions(self, prefix: str, limit: int) -> Sequence[QuerySuggestion]:
        sql = text(
            "SELECT query, historical_count FROM queries WHERE query LIKE :prefix || '%' ORDER BY historical_count DESC, query ASC LIMIT :limit"
        )
        with self._session_factory() as session:  # type: Session
            result = session.execute(sql, {"prefix": prefix, "limit": limit})
            rows = result.fetchall()
        return [QuerySuggestion(query=row[0], historical_count=int(row[1])) for row in rows]
