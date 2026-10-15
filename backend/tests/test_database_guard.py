"""DatabaseGuard: deadline, bulkhead and circuit breaker for read-path database calls (no services needed)."""
import threading
import time

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.database.guard import DatabaseGuard, DatabaseUnavailable


def hang(release: threading.Event):
    def f():
        release.wait(30)
        return "late"
    return f


def test_success_passes_through_with_args():
    g = DatabaseGuard(max_concurrency=2, timeout_s=1.0)
    assert g.call(lambda a, b=0: a + b, 2, b=3) == 5


def test_hung_call_is_bounded_by_the_deadline_then_the_breaker_fails_fast():
    g = DatabaseGuard(max_concurrency=4, timeout_s=0.15, breaker_seconds=30)
    release = threading.Event()
    t0 = time.perf_counter()
    with pytest.raises(DatabaseUnavailable):
        g.call(hang(release))
    assert 0.1 < time.perf_counter() - t0 < 0.6        # the request thread was NOT held for the 30 s hang
    called = []
    t0 = time.perf_counter()
    with pytest.raises(DatabaseUnavailable):
        g.call(lambda: called.append(1))
    assert time.perf_counter() - t0 < 0.05 and called == []     # breaker open: no database work at all
    assert g.stats()["timeouts"] == 1 and g.stats()["rejected_breaker_open"] == 1
    release.set()


def test_bulkhead_rejects_immediately_when_hung_calls_hold_every_slot():
    t = {"now": 0.0}
    g = DatabaseGuard(max_concurrency=2, timeout_s=0.1, breaker_seconds=1.0, clock=lambda: t["now"])
    release = threading.Event()
    for _ in range(2):                                  # two hung calls: each times out, each keeps its worker + slot
        with pytest.raises(DatabaseUnavailable):
            g.call(hang(release))
        t["now"] += 10                                  # let the breaker go half-open so the next call really runs
    t["now"] += 10                                      # breaker window over: next caller is the half-open probe
    t0 = time.perf_counter()
    with pytest.raises(DatabaseUnavailable, match="saturated"):
        g.call(lambda: 1)
    assert time.perf_counter() - t0 < 0.05              # rejected at once, never queued behind the hung workers
    release.set()                                       # database "comes back": hung calls finish, slots free up
    deadline = time.time() + 3
    while time.time() < deadline:
        t["now"] += 10
        try:
            assert g.call(lambda: "ok") == "ok"
            break
        except DatabaseUnavailable:
            time.sleep(0.05)
    else:
        pytest.fail("guard never recovered after the hung calls finished")


def test_half_open_probe_closes_the_breaker_on_success():
    t = {"now": 0.0}
    g = DatabaseGuard(max_concurrency=2, timeout_s=0.1, breaker_seconds=5.0, clock=lambda: t["now"])
    release = threading.Event()
    with pytest.raises(DatabaseUnavailable):
        g.call(hang(release))
    assert g.is_open
    t["now"] += 10
    release.set()
    time.sleep(0.1)                                     # let the hung worker finish and free its slot
    assert g.call(lambda: "probe") == "probe"
    assert not g.is_open and g.call(lambda: "again") == "again"


def test_connection_errors_open_the_breaker_but_sql_errors_do_not():
    g = DatabaseGuard(max_concurrency=2, timeout_s=1.0, breaker_seconds=30)

    def sql_error():
        raise ProgrammingError("SELECT", {}, Exception("syntax"))

    with pytest.raises(ProgrammingError):
        g.call(sql_error)
    assert not g.is_open                                # the database answered; it is alive
    with pytest.raises(ValueError):
        g.call(lambda: (_ for _ in ()).throw(ValueError("bug")))
    assert not g.is_open

    def conn_error():
        raise OperationalError("SELECT", {}, Exception("connection refused"))

    with pytest.raises(OperationalError):
        g.call(conn_error)                              # original exception type is preserved for the 503 handler
    assert g.is_open
    with pytest.raises(DatabaseUnavailable):
        g.call(lambda: 1)


def test_workers_are_daemon_threads_so_a_hung_database_cannot_block_process_exit():
    g = DatabaseGuard(max_concurrency=3, timeout_s=1.0)
    g.call(lambda: 1)
    workers = [t for t in threading.enumerate() if t.name.startswith("db-guard-")]
    assert len(workers) >= 3 and all(w.daemon for w in workers)


def test_many_hung_calls_never_use_more_threads_than_the_concurrency_limit():
    g = DatabaseGuard(max_concurrency=3, timeout_s=0.05, breaker_seconds=0.0001)
    release = threading.Event()
    before = threading.active_count()
    for _ in range(40):
        try:
            g.call(hang(release))
        except DatabaseUnavailable:
            pass
        time.sleep(0.001)
    assert threading.active_count() - before <= 3 + 1
    release.set()


def test_saturation_rejections_do_not_open_the_breaker_and_do_not_lose_the_probe():
    t = {"now": 0.0}
    g = DatabaseGuard(max_concurrency=1, timeout_s=0.1, breaker_seconds=1.0, clock=lambda: t["now"])
    release = threading.Event()
    with pytest.raises(DatabaseUnavailable):
        g.call(hang(release))                           # the only slot is now held by a hung call; breaker open
    t["now"] += 10                                      # half-open: the next caller is granted the probe ...
    with pytest.raises(DatabaseUnavailable, match="saturated"):
        g.call(lambda: 1)                               # ... but there is no slot: rejected, probe grant released
    with pytest.raises(DatabaseUnavailable, match="saturated"):
        g.call(lambda: 1)                               # a lost probe would make this say "circuit open" instead
    release.set()
