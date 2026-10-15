"""Repository behaviour against a REAL PostgreSQL (opt-in, see conftest.py)."""
import math
import secrets
import threading
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from hypothesis import given, settings, strategies as st, HealthCheck
from sqlalchemy import text

from app.database.session import get_session, engine
from app.repositories.query_repository import QueryRepository, _FETCH_SQL
from app.services.normalization import escape_like
from app.services.trending_calculator import QueryState, TrendingCalculator

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(seeded):
    return QueryRepository(get_session)


def names(rows):
    return [r.query for r in rows]


def test_prefix_basic_order_and_limit(repo):
    out = repo.fetch_suggestions("iphone", 3)
    assert names(out) == ["iphone 15 pro case", "iphone 14 pro max case", "iphone"]


def test_ties_are_ordered_by_query_for_deterministic_output(repo):
    assert names(repo.fetch_suggestions("tie", 10)) == ["tie one", "tie three", "tie two"]


@pytest.mark.parametrize("prefix,expected", [
    ("%", []),                          # was: matched EVERY row (wildcard)
    ("_", []),                          # was: matched every non-empty row
    ("a_", ["a_b test"]),               # was: also axb test, abc
    ("a\\", ["a\\b slash"]),            # was: [] (backslash escaped the implicit '%')
    ("100%", ["100% cotton"]),
    ("100%25", []),
    ("a%", []),                         # no row starts with literal "a%"
    ("café", ["café latte"]),
    ("日本", ["日本語 検索"]),
    ("ñ", ["ñandú"]),
])
def test_prefix_matching_is_literal(repo, prefix, expected):
    assert names(repo.fetch_suggestions(prefix, 10)) == expected


@given(prefix=st.text(alphabet="ab%_\\ x", min_size=1, max_size=6), rest=st.text(alphabet="ab%_\\ x", min_size=0, max_size=8))
@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_like_pattern_equals_startswith_property(prefix, rest, pg_dsn):
    cand = prefix + rest
    with get_session() as s:
        got = s.execute(text("SELECT CAST(:s AS text) LIKE :p ESCAPE '\\'"),
                        {"s": cand, "p": escape_like(prefix) + "%"}).scalar()
        neg = s.execute(text("SELECT CAST(:s AS text) LIKE :p ESCAPE '\\'"),
                        {"s": rest, "p": escape_like(prefix) + "%"}).scalar()
    assert got is True
    assert neg == rest.startswith(prefix)


def test_prefix_query_uses_the_text_pattern_ops_index(pg_dsn):
    """The ESCAPE clause + bind parameter must not force a sequential scan on a realistically sized table."""
    with psycopg.connect(pg_dsn, autocommit=True) as c:
        c.execute("TRUNCATE queries RESTART IDENTITY")
        c.execute("INSERT INTO queries (query, historical_count) "
                  "SELECT md5(g::text) || ' ' || g, g % 1000 FROM generate_series(1, 60000) g")
        c.execute("ANALYZE queries")
    with get_session() as s:
        plan = "\n".join(r[0] for r in s.execute(text("EXPLAIN " + _FETCH_SQL.text), {"pattern": "abc%", "limit": 10}))
    assert "idx_query_prefix" in plan, plan
    assert "Seq Scan" not in plan, plan


def test_atomic_upsert_inserts_and_accumulates(repo):
    repo.apply_search_counts({"brand new": 3, "iphone": 2}, 0.5)
    with get_session() as s:
        new = s.execute(text("SELECT historical_count, recent_count FROM queries WHERE query='brand new'")).one()
        old = s.execute(text("SELECT historical_count FROM queries WHERE query='iphone'")).scalar()
    assert tuple(new) == (3, 3.0)
    assert old == 522


def test_sql_decay_matches_reference_calculator(repo):
    last = datetime.now(timezone.utc) - timedelta(hours=2)
    with get_session() as s:
        s.execute(text("UPDATE queries SET recent_count = 10, last_decay_at = :t WHERE query = 'iphone'"), {"t": last})
        s.commit()
    repo.apply_search_counts({"iphone": 3}, 0.5)
    with get_session() as s:
        got = s.execute(text("SELECT recent_count FROM queries WHERE query='iphone'")).scalar()
    [ref] = TrendingCalculator(0.5).compute_decayed_updates({"iphone": 3}, [QueryState("iphone", 520, 10.0, last)])
    assert math.isclose(got, ref.new_recent_count, rel_tol=1e-3)
    assert math.isclose(got, 10 * math.exp(-1.0) + 3, rel_tol=1e-3)


def test_concurrent_flushers_do_not_lose_updates(repo):
    """Regression: the old SELECT -> compute-in-Python -> UPSERT path lost updates when two flushers overlapped."""
    threads, per_thread, rounds = 8, 5, 30
    errors = []

    def work():
        r = QueryRepository(get_session)
        try:
            for _ in range(rounds):
                r.apply_search_counts({"hot": per_thread, "iphone": 1}, 0.5)
        except Exception as e:      # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=work) for _ in range(threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    with get_session() as s:
        hot = s.execute(text("SELECT historical_count FROM queries WHERE query='hot'")).scalar()
        iph = s.execute(text("SELECT historical_count FROM queries WHERE query='iphone'")).scalar()
    assert hot == threads * per_thread * rounds
    assert iph == 520 + threads * rounds


def test_overlapping_batches_in_different_orders_do_not_deadlock(repo):
    keys = [f"k{i}" for i in range(40)]
    errors = []

    def work(order):
        r = QueryRepository(get_session)
        try:
            for _ in range(15):
                r.apply_search_counts({k: 1 for k in order}, 0.5)
        except Exception as e:      # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=work, args=(keys if i % 2 else keys[::-1],)) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    with get_session() as s:
        assert s.execute(text("SELECT sum(historical_count) FROM queries WHERE query LIKE 'k%' AND query ~ '^k[0-9]+$'")).scalar() == 6 * 15 * 40


def test_unpersistable_value_is_rejected_by_the_database_and_rolled_back(repo):
    with pytest.raises(Exception):
        repo.apply_search_counts({"good row": 1, secrets.token_hex(3000): 1}, 0.5)   # > btree max row size
    with get_session() as s:
        assert s.execute(text("SELECT count(*) FROM queries WHERE query='good row'")).scalar() == 0   # atomic batch


def test_ping(repo):
    repo.ping()


def test_batches_are_sent_in_sorted_order_so_concurrent_flushers_lock_rows_consistently():
    """Deterministic version of the deadlock-avoidance property (the threaded test above is probabilistic)."""
    from contextlib import contextmanager
    seen = {}

    class FakeSession:
        def execute(self, sql, params):
            seen["sql"], seen["params"] = str(sql), params

        def commit(self):
            pass

    @contextmanager
    def factory():
        yield FakeSession()

    QueryRepository(factory).apply_search_counts({"zebra": 1, "apple": 2, "mango": 3}, 0.5)
    assert seen["params"]["queries"] == ["apple", "mango", "zebra"]
    assert seen["params"]["deltas"] == [2, 3, 1]
    assert "ORDER BY t.q" in seen["sql"]
