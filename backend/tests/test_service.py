"""SuggestionService with fakes: cache-aside semantics independent of Redis/PostgreSQL."""
import pytest

from app.cache.base import CacheInterface
from app.models.query import QuerySuggestion
from app.services.normalization import suggestion_cache_key
from app.services.suggestion_service import SuggestionService


class Repo:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.calls = []

    def fetch_suggestions(self, prefix, limit):
        self.calls.append((prefix, limit))
        out = [QuerySuggestion(q, c) for q, c in self.rows.items() if q.startswith(prefix)]
        out.sort(key=lambda s: (-s.historical_count, s.query))
        return out[:limit]


class DictCache(CacheInterface):
    def __init__(self):
        self.d = {}
        self.sets = 0

    def get(self, k):
        return self.d.get(k)

    def set(self, k, v, ttl):
        self.sets += 1
        self.d[k] = v

    def delete(self, k):
        self.d.pop(k, None)

    def get_ttl(self, k):
        return -2


def svc(repo=None, cache=None, **kw):
    return SuggestionService(repo or Repo({"iphone": 5, "iphone 12": 3, "ipad": 9}), cache or DictCache(),
                             max_prefix_length=kw.pop("max_prefix_length", 64), default_limit=10,
                             cache_ttl_seconds=300)


def test_miss_then_hit_serves_second_request_without_touching_the_repository():
    s = svc()
    first = s.suggest("IPH ")
    second = s.suggest("iph")
    assert first == second and len(s._repository.calls) == 1
    assert [x.query for x in first.suggestions] == ["iphone", "iphone 12"]


def test_empty_result_is_negatively_cached():
    s = svc()
    assert s.suggest("zzz").suggestions == []
    assert s.suggest("zzz").suggestions == []
    assert len(s._repository.calls) == 1


def test_cache_key_is_built_from_the_normalized_prefix():
    cache = DictCache()
    svc(cache=cache).suggest("  IpH   ")
    assert list(cache.d) == [suggestion_cache_key("iph")]


def test_non_default_limit_bypasses_the_cache_instead_of_returning_wrong_sized_data():
    cache = DictCache()
    s = svc(cache=cache)
    s.suggest("i")                                   # primes the cache with the default limit
    assert len(s.suggest("i", limit=1).suggestions) == 1
    assert len(s.suggest("i").suggestions) == 3
    assert cache.sets == 1


@pytest.mark.parametrize("bad", [{"not": "a list"}, [{"query": "x"}], "garbage", 7, '[{"query":"x","historical_count":1}]', '{"nope":1}'])
def test_malformed_cache_entries_are_treated_as_a_miss_and_overwritten(bad):
    cache = DictCache()
    cache.d[suggestion_cache_key("ip")] = bad
    s = svc(cache=cache)
    out = s.suggest("ip")
    assert [x.query for x in out.suggestions] == ["ipad", "iphone", "iphone 12"]
    assert cache.d[suggestion_cache_key("ip")].startswith('{"prefix":"ip"') and len(s._repository.calls) == 1


def test_cache_failure_degrades_to_database_not_to_an_error():
    class Broken(DictCache):
        def get(self, k):
            return None            # what DistributedCache returns on any Redis error

        def set(self, k, v, ttl):
            pass

    s = svc(cache=Broken())
    assert s.suggest("ip").total_results == 3


def test_validate_and_normalize_contract():
    s = svc(max_prefix_length=5)
    assert s.validate_and_normalize("  AbC ") == "abc"
    for bad in ["", "   ", "toolong", "a\x00"]:
        with pytest.raises(ValueError):
            s.validate_and_normalize(bad)


def test_response_is_deterministic_for_identical_requests_with_ties():
    r = Repo({"tie b": 5, "tie a": 5, "tie c": 5})
    a = svc(repo=r, cache=DictCache()).suggest("tie")
    b = svc(repo=r, cache=DictCache()).suggest("tie")
    assert a == b and [x.query for x in a.suggestions] == ["tie a", "tie b", "tie c"]


# ---- single-flight (concurrent identical misses share one database query) ----------------------
import threading
import time


class SlowRepo(Repo):
    def __init__(self, rows, delay=0.2, fail_first=False):
        super().__init__(rows)
        self.delay, self.fail_first, self._n = delay, fail_first, 0
        self._lock = threading.Lock()

    def fetch_suggestions(self, prefix, limit):
        with self._lock:
            self._n += 1
            n = self._n
        time.sleep(self.delay)
        if self.fail_first and n == 1:
            raise RuntimeError("db hiccup")
        return super().fetch_suggestions(prefix, limit)


def _run_concurrently(s, n, prefix="ip"):
    out, errs = [None] * n, []
    barrier = threading.Barrier(n)

    def work(i):
        barrier.wait()
        try:
            out[i] = s.suggest_json(prefix)
        except Exception as e:
            errs.append(e)

    ts = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out, errs


def test_concurrent_identical_misses_cost_one_database_query():
    repo = SlowRepo({"iphone": 5, "ipad": 9})
    s = svc(repo=repo)
    out, errs = _run_concurrently(s, 40)
    assert not errs and len(repo.calls) == 1
    assert len(set(out)) == 1 and out[0].startswith('{"prefix":"ip"')


def test_different_keys_are_not_serialised_behind_each_other():
    repo = SlowRepo({"iphone": 5, "ipad": 9, "xbox": 1}, delay=0.3)
    s = svc(repo=repo)
    t0 = time.perf_counter()
    ts = [threading.Thread(target=s.suggest_json, args=(p,)) for p in ("ip", "xb", "i", "x")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert time.perf_counter() - t0 < 0.7          # 4 x 0.3 s sequential would be 1.2 s
    assert len(repo.calls) == 4


def test_leader_failure_does_not_poison_followers_and_flight_table_is_cleaned():
    repo = SlowRepo({"iphone": 5}, fail_first=True)
    s = svc(repo=repo)
    out, errs = _run_concurrently(s, 10)
    assert len(errs) == 1                           # only the leader sees the failure
    assert sum(o is not None for o in out) == 9     # followers fell back to their own query
    assert s._flights == {}
    assert s.suggest_json("ip").startswith('{"prefix":"ip"')   # and the next request works normally
