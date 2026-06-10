# Architecture Deep Dive: Distributed Caching System

This document provides a highly detailed architectural review of the TypeAheadX caching layer. 

The caching system was not built in a single iteration. It evolved from a single Redis node (Phase 3) into a horizontally scaled, consistently hashed distributed caching cluster (Phase 4), ultimately supported by active prefix invalidation (Phase 5).

---

## 1. The Strategy: Why We Cache

In a TypeAhead system, the read path is bombarded by keystrokes. While frontend debouncing (250ms) reduces network spam *per user*, global traffic still converges on massive Zipfian "hot prefixes" (e.g., millions of users typing `iph`).

Without a cache, 10,000 distinct users searching for `iphone` triggers 10,000 identical `LIKE 'iph%'` B-Tree reads in PostgreSQL. Caching intercepts this population-level redundancy, absorbing 97%+ of the read traffic and reducing DB load to a fraction of a percent.

---

## 2. Core Components (The "Where")

The cache architecture is located in `backend/app/cache/` and adheres strictly to Dependency Inversion principles.

### A. The Interface (`base.py`)
```python
class CacheInterface(ABC):
    @abstractmethod
    def get(self, key: str) -> Optional[Any]: ...
    @abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: int) -> None: ...
    @abstractmethod
    def delete(self, key: str) -> None: ...
```
**Why**: The FastAPI routers depend on `CacheInterface`, not Redis. This allowed us to hot-swap from `MemoryCache` to `RedisCache` to `DistributedCache` purely via `.env` configuration without altering a single line of business logic.

### B. The Consistent Hash Ring (`consistent_hash_ring.py`)
**What**: The brain of the distributed router.
**Why**: If we used naive modulo hashing (`hash(key) % 3`), adding a 4th Redis node would change the mathematical result for ~75% of all keys, causing a catastrophic cache miss cascade (Thundering Herd) that would crash PostgreSQL.
**How**: 
1. We project the entire hash space onto a 128-bit `MD5` ring.
2. Physical Redis nodes are projected onto this ring.
3. Keys (`"iph"`) are hashed. We use Python's `bisect` library to perform an $O(\log N)$ binary search to find the nearest physical node clockwise on the ring.
4. **Result**: If a node is added or dies, only the keys immediately adjacent to it are affected (reducing key movement from 75% down to 26%).

### C. Virtual Nodes
**The Problem**: Consistent Hashing is great for stability, but terrible for load distribution. A physical node might randomly own 50% of the Hash Ring.
**The Fix**: In `consistent_hash_ring.py`, we implement Virtual Nodes. 
**Why 500?**: Our sensitivity analysis proved that 150 virtual nodes yielded a 10% traffic skew. By setting `VIRTUAL_NODES=500` in the `.env`, we scatter 500 microscopic replicas of each physical node across the ring, reducing variance to `< 2%`.

### D. The Distributed Orchestrator (`distributed_cache.py`)
**What**: Binds the Hash Ring to the physical network connections.
**How it works**:
1. `get("iph")` is called.
2. Orchestrator asks the Ring: "Who owns 'iph'?"
3. Ring returns `redis-b:6380`.
4. Orchestrator executes a Redis `GET` against the TCP connection for `redis-b`.
5. Orchestrator triggers `CacheMetrics.record_hit()` or `miss()`.

---

## 3. The Invalidation Strategy (Phase 5)

Originally, we used a passive 5-minute TTL. This failed in production simulation.

**The Problem**: If a celebrity news event goes viral, the database ranks it #1 immediately. But if the cache for the prefix `"cel"` has a 5-minute TTL, users will see stale data for 5 minutes. 
**The Solution**: Active Prefix Invalidation (`backend/app/write_buffer/batch_worker.py`).

When our asynchronous write buffer flushes new trending data to PostgreSQL, it simultaneously identifies all prefixes related to the new data (e.g., `"c"`, `"ce"`, `"cel"`) and executes `delete()` commands against the Distributed Cache. 

**Result**: The very next user who types `"cel"` triggers a cache miss, forcing the system to read the fresh trending data from PostgreSQL. The cache acts as an infinitely fresh shock absorber.

---

## 4. Observability & Metrics

A cache is a black box without metrics. We implemented an in-memory `CacheMetrics` singleton that tracks:
- Global Hits, Misses, Sets, Errors.
- Per-node hit distribution.

This is exposed via the `GET /metrics` and `GET /cache/debug` endpoints, allowing us to mathematically verify our Consistent Hashing distribution and our 97% cache hit rates in real-time.

---

## 5. Known Limitations

As documented in our Architecture review, this design accepts a few FAANG-scale trade-offs:
1. **Hot Shards**: Consistent hashing distributes the *keyspace*, not the *traffic*. If `"iphone"` represents 50% of all global search traffic, the single Redis node owning `"iphone"` will still melt. (Requires L1 local caching or key-replication).
2. **Stampedes**: During an active invalidation, if 10,000 users type `"iph"` simultaneously, all 10,000 will miss the cache and hit PostgreSQL concurrently. (Requires request coalescing / singleflight).
