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

    def get_queries_by_names(self, names: Sequence[str]) -> Sequence[QuerySuggestion]:
        # Returns raw DB rows mapped to a helper class or tuple. 
        # Actually, let's use the QueryState dataclass we created in trending_calculator.py
        # For simplicity without circular imports, we can return tuples or dicts
        # Let's import QueryState here or just return raw rows.
        from ..services.trending_calculator import QueryState
        if not names:
            return []
            
        sql = text(
            "SELECT query, historical_count, recent_count, last_decay_at FROM queries WHERE query = ANY(:names)"
        )
        with self._session_factory() as session:
            result = session.execute(sql, {"names": list(names)})
            rows = result.fetchall()
            
        return [
            QueryState(
                query=row[0],
                historical_count=int(row[1]),
                recent_count=float(row[2]),
                last_decay_at=row[3]
            )
            for row in rows
        ]
        
    def upsert_batch_with_trending(self, updates: Sequence['DecayedUpdate']) -> None:
        """
        Takes a list of DecayedUpdate and upserts them into the database.
        """
        if not updates:
            return
            
        sql = text("""
            INSERT INTO queries (query, historical_count, recent_count, last_decay_at)
            VALUES (:query, :historical_count, :recent_count, :last_decay_at)
            ON CONFLICT (query) DO UPDATE SET
                historical_count = EXCLUDED.historical_count,
                recent_count = EXCLUDED.recent_count,
                last_decay_at = EXCLUDED.last_decay_at
        """)
        
        # Prepare parameters
        params = [
            {
                "query": u.query,
                "historical_count": u.historical_count,
                "recent_count": u.new_recent_count,
                "last_decay_at": u.last_decay_at
            }
            for u in updates
        ]
        
        with self._session_factory() as session:
            session.execute(sql, params)
            session.commit()
