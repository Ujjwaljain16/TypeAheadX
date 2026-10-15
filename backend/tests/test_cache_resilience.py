"""Cache-layer failure behaviour with a fake redis client (no network)."""
import socket
import threading
import time

import pytest

from app.cache import redis_node as rn
from app.cache import distributed_cache as dc
from app.cache.metrics import CacheMetrics
from app.database.config import Settings


class FakeRedis:
    """Stand-in for redis.Redis; behaviour is controlled per port through FakeRedis.state."""
    state: dict = {}
    calls: dict = {}
    deletes: list = []

    def __init__(self, host, port, **kw):
        self.port = port
        self.kw = kw
        FakeRedis.calls.setdefault(port, 0)
        FakeRedis.state.setdefault(port, {"up": True, "data": {}})

    def _op(self):
        FakeRedis.calls[self.port] += 1
        if not FakeRedis.state[self.port]["up"]:
            raise ConnectionError("down")

    def ping(self):
        self._op()

    def get(self, k):
        self._op()
        return FakeRedis.state[self.port]["data"].get(k)

    def set(self, k, v, ex=None):
        self._op()
        FakeRedis.state[self.port]["data"][k] = v

    def delete(self, *ks):
        self._op()
        for k in ks:
            FakeRedis.state[self.port]["data"].pop(k, None)
        FakeRedis.deletes.append((self.port, len(ks)))

    def ttl(self, k):
        self._op()
        return 100


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    FakeRedis.state, FakeRedis.calls, FakeRedis.deletes = {}, {}, []
    monkeypatch.setattr(rn.redis, "Redis", FakeRedis)
    CacheMetrics.reset()
    yield


def cache(monkeypatch, breaker=5.0):
    monkeypatch.setattr(dc, "get_settings", lambda: Settings(REDIS_NODES="h:1,h:2,h:3", REDIS_BREAKER_SECONDS=breaker,
                                                             VIRTUAL_NODES=200))
    return dc.DistributedCache()


def keys_for(c, port, n=20):
    name = f"h:{port}"
    return [k for k in (f"suggestion:k{i}" for i in range(5000)) if c.ring.get_node(k).physical_node == name][:n]


def test_dead_node_costs_one_failed_call_then_is_skipped_without_network_io(monkeypatch):
    c = cache(monkeypatch)
    ks = keys_for(c, 2)
    FakeRedis.state[2]["up"] = False
    before = FakeRedis.calls[2]
    assert c.get(ks[0]) is None                      # discovers the failure (1 network call)
    after_first = FakeRedis.calls[2]
    for k in ks:                                     # many more operations: none touch the dead node
        assert c.get(k) is None
        c.set(k, [1], 60)
        c.delete(k)
    assert after_first - before == 1
    assert FakeRedis.calls[2] == after_first
    m = CacheMetrics.get_metrics()
    assert m["breaker_skips"] >= 3 * len(ks) and m["errors"] == 1


def test_healthy_nodes_are_unaffected_by_a_dead_node(monkeypatch):
    c = cache(monkeypatch)
    FakeRedis.state[2]["up"] = False
    c.get(keys_for(c, 2)[0])
    for k in keys_for(c, 1) + keys_for(c, 3):
        c.set(k, ["v"], 60)
        assert c.get(k) == ["v"]


def test_half_open_probe_allows_exactly_one_caller_and_recovery_closes_the_breaker(monkeypatch):
    t = {"now": 1000.0}
    node = rn.RedisNode("n", "h", 9, breaker_seconds=5.0, clock=lambda: t["now"])
    node.record_failure()
    assert node.allow() is False
    t["now"] += 7                                     # window (<= 5 s * 1.2 jitter) elapsed
    results = []
    barrier = threading.Barrier(16)

    def probe():
        barrier.wait()
        results.append(node.allow())

    ts = [threading.Thread(target=probe) for _ in range(16)]
    [x.start() for x in ts]
    [x.join() for x in ts]
    assert results.count(True) == 1                   # a single probe, no thundering herd on a recovering node
    node.record_success()
    assert node.allow() and not node.is_open


def test_failed_probe_reopens_the_breaker(monkeypatch):
    t = {"now": 0.0}
    node = rn.RedisNode("n", "h", 9, breaker_seconds=5.0, clock=lambda: t["now"])
    node.record_failure()
    t["now"] += 7
    assert node.allow()
    node.record_failure()
    assert node.allow() is False
    t["now"] += 7
    assert node.allow() is True


def test_node_down_at_startup_recovers_instead_of_being_disabled_forever(monkeypatch):
    FakeRedis.state[2] = {"up": False, "data": {}}   # down while the application starts
    c = cache(monkeypatch, breaker=0.05)
    k = keys_for(c, 2)[0]
    assert c.get(k) is None
    FakeRedis.state[2]["up"] = True                   # node comes back
    time.sleep(0.2)
    c.set(k, ["v"], 60)
    assert c.get(k) == ["v"]                          # original code: client was None -> never used again


def test_corrupt_entry_is_a_miss_and_does_not_trip_the_breaker(monkeypatch):
    c = cache(monkeypatch)
    k = keys_for(c, 1)[0]
    FakeRedis.state[1]["data"][k] = "{not json"
    assert c.get(k) is None
    assert not c.nodes["h:1"].is_open
    assert CacheMetrics.get_metrics()["errors"] == 1


def test_empty_ring_degrades_to_misses_not_exceptions(monkeypatch):
    monkeypatch.setattr(dc, "get_settings", lambda: Settings(REDIS_NODES=""))
    c = dc.DistributedCache()
    assert c.get("suggestion:x") is None
    c.set("suggestion:x", [1], 60)
    c.delete("suggestion:x")
    assert c.get_debug_info("suggestion:x")["exists"] is False      # was a KeyError -> HTTP 500


def test_blackholed_node_is_bounded_by_the_timeout_and_then_skipped(monkeypatch):
    """Real sockets: connect to a non-routable address. First call is bounded by the timeout; later calls are instant."""
    monkeypatch.undo()                                # use the real redis client for this test
    from app.cache.redis_node import RedisNode
    s = socket.socket()
    s.bind(("127.0.0.1", 0)); s.listen(0)             # accepts connections at TCP level but never answers (backlog 0)
    port = s.getsockname()[1]
    try:
        t_start = time.perf_counter()
        node = RedisNode("bh", "127.0.0.1", port, timeout=0.2, breaker_seconds=30)
        assert node.is_open                           # start-up ping timed out -> breaker already open
        assert time.perf_counter() - t_start < 1.5   # ... and that took about one timeout, not 6 s of retries
        t0 = time.perf_counter()
        for _ in range(100):
            assert node.allow() is False
        assert time.perf_counter() - t0 < 0.05
    finally:
        s.close()


def test_delete_many_is_one_round_trip_per_node_and_skips_dead_nodes(monkeypatch):
    c = cache(monkeypatch)
    ks = [f"suggestion:p{i}" for i in range(300)]
    for k in ks:
        c.set(k, [1], 60)
    FakeRedis.deletes.clear()
    c.delete_many(ks)
    # 300 keys: a handful of <=100-key commands instead of 300 round trips
    assert len(FakeRedis.deletes) <= 6 and sum(n for _, n in FakeRedis.deletes) == 300
    assert max(n for _, n in FakeRedis.deletes) <= 100
    assert all(c.get(k) is None for k in ks)

    for k in ks:
        c.set(k, [1], 60)
    FakeRedis.state[2]["up"] = False
    c.delete_many(ks)                                  # first call discovers the failure ...
    FakeRedis.deletes.clear()
    c.delete_many(ks)                                  # ... then the dead node is skipped without I/O
    assert all(port != 2 for port, _ in FakeRedis.deletes)


def test_a_failed_operation_is_bounded_by_the_timeout_not_multiplied_by_client_retries(monkeypatch):
    """Regression: redis-py's default retry policy turned a 0.25 s timeout into 5-8 s per failed call."""
    monkeypatch.undo()                                # real redis client
    from app.cache.redis_node import RedisNode
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(0)                                       # TCP-accepts, never answers
    port = s.getsockname()[1]
    try:
        node = RedisNode("bh2", "127.0.0.1", port, timeout=0.25, breaker_seconds=30)
        t0 = time.perf_counter()
        try:
            node.client.get("x")
        except Exception:
            pass
        assert time.perf_counter() - t0 < 1.0
    finally:
        s.close()
