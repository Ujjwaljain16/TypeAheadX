from __future__ import annotations

from typing import Mapping, Sequence

from sqlalchemy import text

from ..database.guard import DatabaseGuard
from ..models.query import QuerySuggestion
from ..services.normalization import escape_like

# Prefix match is expressed as LIKE <escaped-prefix>% ESCAPE '\' so that '%', '_' and '\'
# typed by a user are matched literally. The pattern is a bind parameter; with the
# text_pattern_ops index PostgreSQL derives the range  query >= p AND query < p'  from it.
#
# Ranking (docs/ARCHITECTURE.md section 4):  score = historical_count + beta * recent_count * exp(-lambda * hours)
# where `hours` is the time since recent_count was last updated. The decay is evaluated at READ time:
# recent_count is only rewritten when a query is searched, so a stored value for a query nobody searches any
# more would otherwise never fade. The expression is computed only for rows matching the prefix (the
# prefix index narrows them first), so it is not indexable and does not need to be. Rows with
# recent_count = 0 (everything in the loaded dataset until searched) sort exactly as before:
# historical_count DESC, query ASC.
_FETCH_SQL = text(
    "SELECT query, historical_count FROM queries "
    "WHERE query LIKE :pattern ESCAPE '\\' "
    "ORDER BY (historical_count + CAST(:beta AS double precision) * recent_count "
    "         * exp(-CAST(:lam AS double precision) "
    "               * GREATEST(EXTRACT(EPOCH FROM (NOW() - last_decay_at)), 0) / 3600.0)) DESC, "
    "         historical_count DESC, query ASC LIMIT :limit"
)

# Atomic merge of a batch of buffered search counts.
#  * historical_count and the decayed recent_count are updated *in SQL* under the row lock taken by
#    ON CONFLICT DO UPDATE, so concurrent flushers (several API workers/instances) cannot lose updates
#    (the previous SELECT-then-UPSERT computed new values in Python from a stale read).
#  * Decay uses the database clock (NOW()), which removes clock skew between application hosts.
#    recent_count' = recent_count * exp(-lambda * hours_since_last_decay) + delta
#    (identical formula to services.trending_calculator.TrendingCalculator)
_UPSERT_SQL = text(
    """
    INSERT INTO queries (query, historical_count, recent_count, last_decay_at, last_searched_at)
    SELECT t.q, t.d, t.d, NOW(), NOW()
    FROM unnest(CAST(:queries AS text[]), CAST(:deltas AS bigint[])) AS t(q, d)
    ORDER BY t.q
    ON CONFLICT (query) DO UPDATE SET
        historical_count = queries.historical_count + EXCLUDED.historical_count,
        recent_count     = queries.recent_count
                           * exp(-CAST(:lam AS double precision)
                                 * GREATEST(EXTRACT(EPOCH FROM (NOW() - queries.last_decay_at)), 0) / 3600.0)
                           + EXCLUDED.recent_count,
        last_decay_at    = GREATEST(queries.last_decay_at, NOW()),
        last_searched_at = NOW()
    """
)


class QueryRepository:
    def __init__(self, session_factory, trending_beta: float = 0.0, decay_lambda: float = 0.5,
                 guard: DatabaseGuard | None = None):
        """session_factory should be a context manager that yields a SQLAlchemy Session.

        ``trending_beta`` weights the (read-time decayed) recent count in the ranking score; 0 means
        "historical popularity only". ``decay_lambda`` is per hour and must match the write path."""
        self._session_factory = session_factory
        self._beta = float(trending_beta)
        self._lambda = float(decay_lambda)
        # Read-path calls (fetch_suggestions, ping) go through the guard when one is given. Writes never do:
        # a timed-out write may still be executed later, so it must not be retried or re-queued.
        self._guard = guard

    def fetch_suggestions(self, prefix: str, limit: int) -> Sequence[QuerySuggestion]:
        if self._guard is not None:
            return self._guard.call(self._fetch, prefix, limit)
        return self._fetch(prefix, limit)

    def _fetch(self, prefix: str, limit: int) -> Sequence[QuerySuggestion]:
        params = {"pattern": escape_like(prefix) + "%", "limit": limit, "beta": self._beta, "lam": self._lambda}
        with self._session_factory() as session:  # type: Session
            rows = session.execute(_FETCH_SQL, params).fetchall()
        return [QuerySuggestion(query=row[0], historical_count=int(row[1])) for row in rows]

    def apply_search_counts(self, counts: Mapping[str, int], decay_lambda: float) -> None:
        """Atomically add ``counts`` (query -> number of searches) in a single transaction.

        Rows are inserted in sorted order so that concurrent flushers lock rows in the same
        order and cannot deadlock each other.
        """
        if not counts:
            return
        # ONE statement / one round trip for the whole batch (arrays + unnest) instead of N pipelined
        # statements; ORDER BY in the SELECT fixes the row-lock order across concurrent flushers.
        items = sorted(counts.items())
        params = {"queries": [q for q, _ in items], "deltas": [int(n) for _, n in items], "lam": float(decay_lambda)}
        with self._session_factory() as session:
            session.execute(_UPSERT_SQL, params)
            session.commit()

    def ping(self) -> None:
        if self._guard is not None:
            self._guard.call(self._ping)
        else:
            self._ping()

    def _ping(self) -> None:
        with self._session_factory() as session:
            session.execute(text("SELECT 1"))
