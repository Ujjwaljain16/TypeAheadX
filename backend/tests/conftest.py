"""Test configuration.

Two kinds of tests live here:

* unit tests   - no external services; always run.
* integration  - need a REAL PostgreSQL and REAL Redis. They are opt-in and are skipped
                 (with a reason) unless these variables are set:

      TAX_TEST_PG_DSN         postgresql://user:pw@localhost:PORT/<name>_test   (database name MUST end in _test)
      TAX_TEST_REDIS_NODES    localhost:P1,localhost:P2,localhost:P3            (flushed by the tests!)

  With the disposable stack from benchmarks/docker-compose.bench.yml:

      source benchmarks/env.sh      # sets both variables (database typeaheadx_test)

Safety: the database is created on demand, but only on localhost and only if its name ends with
``_test``; Redis is only touched when TAX_TEST_REDIS_NODES is given explicitly.
"""
from __future__ import annotations

import os
import pathlib
import re
import urllib.parse

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent
PG_DSN = os.environ.get("TAX_TEST_PG_DSN")
REDIS_NODES = os.environ.get("TAX_TEST_REDIS_NODES")
INTEGRATION = bool(PG_DSN and REDIS_NODES)

if INTEGRATION:
    _u = urllib.parse.urlparse(PG_DSN)
    assert _u.hostname in ("localhost", "127.0.0.1", "::1"), "refusing non-local test database"
    assert re.fullmatch(r"[A-Za-z0-9_]+_test", _u.path.lstrip("/")), "test database name must end in _test"
    # Must be set BEFORE `app` is imported: the SQLAlchemy engine and settings are created at import time.
    os.environ["DATABASE_URL"] = PG_DSN.replace("postgresql://", "postgresql+psycopg://", 1)
    os.environ["REDIS_NODES"] = REDIS_NODES
    os.environ["CACHE_PROVIDER"] = "distributed"
    os.environ["WRITE_BUFFER_FLUSH_INTERVAL"] = "3600"   # tests flush explicitly
    os.environ["WRITE_BUFFER_SIZE"] = "1000000"
    os.environ["CACHE_TTL_SECONDS"] = "300"
    os.environ["DB_QUERY_TIMEOUT_SECONDS"] = "0.5"      # fast deadline/breaker so hung-database tests are quick
    os.environ["DB_BREAKER_SECONDS"] = "1"

SEED_ROWS = [
    ("iphone 15 pro case", 987), ("iphone 14 pro max case", 908), ("iphone", 520), ("iphone 13 case", 381),
    ("iphone 12 case", 227), ("ipad", 300), ("100% cotton", 40), ("a_b test", 30), ("axb test", 99),
    ("a\\b slash", 20), ("abc", 10), ("café latte", 50), ("cafe au lait", 60), ("ñandú", 5),
    ("日本語 検索", 7), ("tie one", 5), ("tie two", 5), ("tie three", 5),
]


def pytest_collection_modifyitems(config, items):
    if INTEGRATION:
        return
    skip = pytest.mark.skip(reason="integration test: set TAX_TEST_PG_DSN and TAX_TEST_REDIS_NODES (see tests/conftest.py)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: needs real PostgreSQL and Redis (opt-in)")


@pytest.fixture(scope="session")
def pg_dsn():
    if not INTEGRATION:
        pytest.skip("integration not configured")
    import psycopg

    u = urllib.parse.urlparse(PG_DSN)
    name = u.path.lstrip("/")
    admin = u._replace(path="/postgres").geturl()
    with psycopg.connect(admin, autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            c.execute(f'CREATE DATABASE "{name}"')
    with psycopg.connect(PG_DSN, autocommit=True) as c:
        c.execute((BACKEND / "schema.sql").read_text(encoding="utf-8"))
    return PG_DSN


@pytest.fixture
def seeded(pg_dsn):
    """Reset the test database to the small deterministic fixture dataset."""
    import psycopg

    with psycopg.connect(pg_dsn, autocommit=True) as c:
        c.execute("TRUNCATE queries RESTART IDENTITY")
        with c.cursor() as cur:
            cur.executemany("INSERT INTO queries (query, historical_count) VALUES (%s, %s)", SEED_ROWS)
        c.execute("ANALYZE queries")
    return SEED_ROWS


@pytest.fixture
def redis_clean(pg_dsn):
    import redis

    clients = []
    for node in REDIS_NODES.split(","):
        host, port = node.strip().split(":")
        c = redis.Redis(host=host, port=int(port))
        c.flushall()
        clients.append(c)
    return clients


@pytest.fixture
def client(seeded, redis_clean):
    """TestClient with the real lifespan (batch worker started, cache connected)."""
    from fastapi.testclient import TestClient

    from app.cache.metrics import CacheMetrics
    from app.write_buffer.buffer import write_buffer
    from app.write_buffer.metrics import write_metrics, WriteMetricsData
    from app.main import app

    CacheMetrics.reset()
    write_buffer.flush()
    write_buffer.max_unique = 50_000
    write_metrics.data = WriteMetricsData()
    with TestClient(app) as c:
        yield c
