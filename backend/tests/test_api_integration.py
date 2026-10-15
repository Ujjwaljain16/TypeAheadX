"""End-to-end API behaviour with REAL PostgreSQL + REAL Redis (opt-in, see conftest.py).

Each test documents a defect that was reproduced on the pre-audit code (finding ids in comments)."""
import secrets

import pytest
from sqlalchemy.exc import OperationalError

from app.write_buffer.batch_worker import batch_worker
from app.write_buffer.buffer import write_buffer

pytestmark = pytest.mark.integration


def q(client, prefix):
    r = client.get("/suggest", params={"q": prefix})
    assert r.status_code == 200, r.text
    return [s["query"] for s in r.json()["suggestions"]]


# --- F-002: LIKE wildcards in user input ---------------------------------------------------
@pytest.mark.parametrize("prefix,expected", [("%", []), ("_", []), ("a_", ["a_b test"]),
                                             ("a\\", ["a\\b slash"]), ("100%", ["100% cotton"])])
def test_wildcard_characters_are_literal(client, prefix, expected):
    assert q(client, prefix) == expected


# --- F-003: invalidation key mismatch -> stale cache after writes ---------------------------
def test_search_then_flush_makes_the_new_query_visible_despite_a_cached_empty_result(client):
    assert q(client, "zzq") == []                       # negative result is cached (TTL 300 s)
    for _ in range(3):
        assert client.post("/search", json={"query": "zzqtest"}).status_code == 200
    batch_worker.flush()
    assert q(client, "zzq") == ["zzqtest"]              # was: [] until the TTL expired


def test_flush_updates_ranking_for_a_cached_prefix(client):
    before = q(client, "tie")
    assert before == ["tie one", "tie three", "tie two"]
    client.post("/search", json={"query": "TIE  Two"})   # also exercises write-path normalization
    batch_worker.flush()
    assert q(client, "tie") == ["tie two", "tie one", "tie three"]


# --- F-004: write-path normalization / validation ------------------------------------------
def test_write_path_normalizes_like_the_read_path(client):
    assert client.post("/search", json={"query": "  Dbl   SPACE  Test "}).status_code == 200
    batch_worker.flush()
    assert q(client, "dbl space") == ["dbl space test"]  # was stored with double spaces and unreachable


@pytest.mark.parametrize("bad", ["x" * 201, "a\x00b", "ctl\x01"])
def test_write_path_rejects_unpersistable_queries(client, bad):
    r = client.post("/search", json={"query": bad})
    assert r.status_code == 400
    assert write_buffer.get_size() == 0


def test_write_path_rejects_lone_surrogate_sent_as_json_escape(client):
    """httpx cannot encode a lone surrogate, so send the JSON escape sequence as raw bytes."""
    r = client.post("/search", content=rb'{"query": "bad\ud800"}', headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert write_buffer.get_size() == 0


@pytest.mark.parametrize("empty", ["", "   ", "\n\t"])
def test_write_path_empty_is_ignored_with_200(client, empty):
    r = client.post("/search", json={"query": empty})
    assert r.status_code == 200 and r.json() == {"message": "Empty query ignored"}


def test_incompressible_oversize_query_no_longer_poisons_the_batch(client):
    """Before: a 6000-char random query made the whole flush fail and silently dropped 4 good events."""
    client.post("/search", json={"query": secrets.token_hex(3000)})
    for i in range(4):
        client.post("/search", json={"query": f"zzpoisongood{i}"})
    batch_worker.flush()
    assert q(client, "zzpoisongood") == [f"zzpoisongood{i}" for i in range(4)]


def test_write_buffer_is_bounded_and_reports_backpressure(client):
    write_buffer.max_unique = 3
    codes = [client.post("/search", json={"query": f"flood{i}"}).status_code for i in range(6)]
    assert codes == [200, 200, 200, 503, 503, 503]
    assert client.post("/search", json={"query": "flood0"}).status_code == 200   # existing key still counted
    m = client.get("/write/metrics").json()
    assert m["events_dropped"] == 3 and m["buffer_current_size"] == 3


# --- read-path input handling ---------------------------------------------------------------
@pytest.mark.parametrize("raw", ["%00", "a%00b", "x" * 65, "%0A", "%EF%BF%BD" * 70])
def test_read_path_rejects_bad_input_with_400_never_500(client, raw):
    r = client.get(f"/suggest?q={raw}")
    assert r.status_code == 400


def test_unicode_whitespace_and_case_are_normalized(client):
    assert q(client, "  CAFÉ ") == ["café latte"]
    assert q(client, "cafe　au") == ["cafe au lait"]
    assert q(client, "é") == []                       # no crash on decomposed input
    assert q(client, "ñ") == ["ñandú"]                # NFC: n + combining tilde == ñ


def test_missing_q_is_422(client):
    assert client.get("/suggest").status_code == 422


# --- operability ------------------------------------------------------------------------------
def test_ready_reports_database_health(client, monkeypatch):
    assert client.get("/ready").json() == {"status": "ready"}
    from app.repositories import query_repository

    def boom(self):
        raise OperationalError("SELECT 1", {}, Exception("db down"))
    monkeypatch.setattr(query_repository.QueryRepository, "ping", boom)
    assert client.get("/ready").status_code == 503


def test_database_outage_maps_to_503_not_a_stack_trace(client, monkeypatch):
    from app.repositories import query_repository

    def boom(self, prefix, limit):
        raise OperationalError("SELECT", {}, Exception("db down: password=secret"))
    monkeypatch.setattr(query_repository.QueryRepository, "fetch_suggestions", boom)
    r = client.get("/suggest?q=neverCached")
    assert r.status_code == 503 and "secret" not in r.text and r.headers["retry-after"] == "1"


def test_debug_endpoints_can_be_disabled(client, monkeypatch):
    from app.api import cache as cache_api
    from app.database.config import Settings

    assert client.get("/cache/debug", params={"prefix": "iph"}).status_code == 200
    monkeypatch.setattr(cache_api, "get_settings", lambda: Settings(ENABLE_DEBUG_ENDPOINTS="false"))
    assert client.get("/cache/debug", params={"prefix": "iph"}).status_code == 404
    assert client.get("/cache/metrics").status_code == 404


def test_cache_debug_uses_the_normalized_key(client):
    q(client, "IPH")
    assert client.get("/cache/debug", params={"prefix": " IPH "}).json()["exists"] is True


def test_cors_has_no_credentials_with_wildcard_origin(client):
    r = client.options("/suggest", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert r.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in r.headers


def test_metrics_endpoints_expose_new_write_counters(client):
    m = client.get("/metrics").json()["write_buffer"]
    assert {"flush_failures", "events_requeued", "events_dropped", "max_flush_duration_ms"} <= set(m)


def test_graceful_shutdown_flushes_buffered_events(seeded, redis_clean):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        c.post("/search", json={"query": "shutdown flush probe"})
        assert write_buffer.get_size() == 1
    # leaving the context runs lifespan shutdown -> BatchWorker.stop() -> final flush
    from app.database.session import get_session
    from sqlalchemy import text
    with get_session() as s:
        assert s.execute(text("SELECT historical_count FROM queries WHERE query='shutdown flush probe'")).scalar() == 1


def test_response_time_header_present_on_success_and_error_responses(client):
    for url in ("/suggest?q=iph", "/suggest?q=", "/health", "/nope"):
        r = client.get(url)
        assert float(r.headers["x-response-time-ms"]) >= 0, url


def test_oversized_request_body_is_rejected_before_being_buffered(client):
    big = b'{"query": "' + b"a" * 100_000 + b'"}'
    r = client.post("/search", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413
    # chunked / undeclared length bodies are limited too
    def gen():
        for _ in range(100):
            yield b"x" * 1000
    r = client.post("/search", content=gen(), headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert write_buffer.get_size() == 0
    assert client.post("/search", json={"query": "small body is fine"}).status_code == 200


def test_searches_make_a_query_trend_end_to_end(client):
    """F-10: recent activity must influence what /suggest returns (it did not before the audit)."""
    assert q(client, "iphone")[0] == "iphone 15 pro case"
    for _ in range(120):
        assert client.post("/search", json={"query": "iphone 12 case"}).status_code == 200
    batch_worker.flush()
    # 227 + 120 historical, plus 10 * 120 recent  >>  987
    assert q(client, "iphone")[0] == "iphone 12 case"
    r = client.get("/suggest", params={"q": "iphone"}).json()
    assert r["suggestions"][0]["historical_count"] == 347      # the displayed count stays the historical count
