"""BatchWorker behaviour with fake collaborators (no database, no Redis)."""
import time

from app.cache.base import CacheInterface
from app.database.config import Settings
from app.services.normalization import suggestion_cache_key
from app.services.suggestion_service import SuggestionService
from app.write_buffer.batch_worker import BatchWorker
from app.write_buffer.buffer import WriteBuffer
from app.write_buffer.metrics import WriteMetrics


class FakeRepo:
    def __init__(self, fail_on=None, down=False):
        self.rows = {}
        self.calls = 0
        self.fail_on = set(fail_on or [])
        self.down = down

    def apply_search_counts(self, counts, lam):
        self.calls += 1
        if self.down:
            raise ConnectionError("db down")
        if self.fail_on & set(counts):
            raise ValueError("poison row")
        for q, n in counts.items():
            self.rows[q] = self.rows.get(q, 0) + n

    def ping(self):
        if self.down:
            raise ConnectionError("db down")


class FakeCache(CacheInterface):
    def __init__(self):
        self.deleted = []
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl):
        self.store[key] = value

    def delete(self, key):
        self.deleted.append(key)

    def get_ttl(self, key):
        return -2


def make(repo=None, buffer=None, cache=None):
    buf = buffer if buffer is not None else WriteBuffer()
    w = BatchWorker(settings=Settings(), repository=repo or FakeRepo(), cache=cache or FakeCache(),
                    buffer=buf, metrics=WriteMetrics())
    return w, buf


def test_successful_flush_persists_and_records_metrics():
    w, buf = make()
    for q in ["a", "a", "a", "b"]:
        buf.increment(q)
    w.flush()
    assert w.repository.rows == {"a": 3, "b": 1}
    snap = w.metrics.get_snapshot()
    assert (snap.flushes_executed, snap.db_writes_executed, snap.db_writes_avoided) == (1, 2, 2)
    assert buf.get_size() == 0


def test_transient_db_failure_requeues_everything_and_nothing_is_lost():
    repo = FakeRepo(down=True)
    w, buf = make(repo)
    for q in ["a", "a", "b"]:
        buf.increment(q)
    w.flush()
    assert buf.flush() == {"a": 2, "b": 1}          # all events are back in the buffer
    snap = w.metrics.get_snapshot()
    assert snap.flush_failures == 1 and snap.events_requeued == 3 and snap.events_dropped == 0
    assert snap.flushes_executed == 0


def test_recovery_after_outage_persists_requeued_events_exactly_once():
    repo = FakeRepo(down=True)
    w, buf = make(repo)
    for q in ["a", "a", "b"]:
        buf.increment(q)
    w.flush()
    repo.down = False
    buf.increment("a")
    w.flush()
    assert repo.rows == {"a": 3, "b": 1}


def test_poison_row_is_isolated_and_good_rows_still_persist():
    """Regression: one unpersistable row used to make the whole batch (and its events) vanish."""
    repo = FakeRepo(fail_on={"POISON"})
    w, buf = make(repo)
    for q in ["g1", "g2", "POISON", "g3", "g4"]:
        buf.increment(q)
    w.flush()
    assert repo.rows == {"g1": 1, "g2": 1, "g3": 1, "g4": 1}
    snap = w.metrics.get_snapshot()
    assert snap.events_dropped == 1 and snap.flush_failures == 0
    assert buf.get_size() == 0


def test_partial_failure_during_bisect_requeues_only_the_uncommitted_part():
    class Flaky(FakeRepo):
        def apply_search_counts(self, counts, lam):
            self.calls += 1
            if len(counts) > 2:
                raise ValueError("batch too big")            # force a bisect
            if "d" in counts:                                 # the DB then goes away
                self.down = True
            if self.down:
                raise ConnectionError("db down")
            for q, n in counts.items():
                self.rows[q] = self.rows.get(q, 0) + n

    repo = Flaky()
    w, buf = make(repo)
    for q in ["a", "b", "c", "d"]:
        buf.increment(q)
    w.flush()
    assert repo.rows == {"a": 1, "b": 1}                      # first half committed
    assert buf.flush() == {"c": 1, "d": 1}                    # only the remainder is re-queued (no double count)


def test_requeue_beyond_buffer_bound_counts_the_loss():
    repo = FakeRepo(down=True)
    buf = WriteBuffer(max_unique=3)
    w, _ = make(repo, buf)
    for q in ["a", "b", "c"]:
        buf.increment(q)
    # While the (failing) flush is in flight new distinct events fill the buffer again.
    orig = repo.apply_search_counts

    def fill_then_fail(counts, lam):
        for q in ["x", "y", "z"]:
            buf.increment(q)
        return orig(counts, lam)

    repo.apply_search_counts = fill_then_fail
    w.flush()
    snap = w.metrics.get_snapshot()
    assert snap.flush_failures == 1 and snap.events_dropped == 3 and snap.events_requeued == 0
    assert buf.get_size() == 3


def test_invalidation_deletes_exactly_the_keys_the_read_path_uses():
    """Regression: invalidation used 'suggest:<prefix>' while reads used 'suggestion:<prefix>'."""
    cache = FakeCache()
    w, buf = make(cache=cache)
    buf.increment("iphone case")
    w.flush()
    expected = {suggestion_cache_key("iphone case"[:i]) for i in range(1, len("iphone case") + 1)}
    assert set(cache.deleted) == expected

    class R:
        def fetch_suggestions(self, p, n):
            return []

    svc = SuggestionService(R(), cache, max_prefix_length=64, default_limit=10, cache_ttl_seconds=60)
    for p in ("i", "iph", "iphone c"):
        svc.suggest(p)
    assert set(cache.store) and set(cache.store) <= expected     # every key a read creates gets invalidated


def test_final_flush_on_stop_even_if_loop_never_started():
    w, buf = make()
    buf.increment("x")
    w.stop()
    assert w.repository.rows == {"x": 1}


def test_loop_flushes_by_size_threshold_and_survives_exceptions():
    w, buf = make()
    w.settings = Settings(WRITE_BUFFER_SIZE=2, WRITE_BUFFER_FLUSH_INTERVAL=3600)
    calls = {"n": 0}
    real = w.flush

    def boom():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("unexpected")
        real()

    w.flush = boom
    buf.increment("a")
    buf.increment("b")
    w.start()
    deadline = time.time() + 8
    while time.time() < deadline and w.repository.rows != {"a": 1, "b": 1}:
        time.sleep(0.1)
    w._stop_event.set()
    w._thread.join(3)
    assert w.repository.rows == {"a": 1, "b": 1}      # loop survived the first exception and retried
