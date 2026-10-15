# Consistent hashing

## Problem
With `N` cache nodes, `hash(key) % N` remaps ≈ (N−1)/N of the keys whenever `N` changes: adding a 4th node to 3 invalidates ≈ 75 % of the cache at once.

## Implementation (`backend/app/cache/consistent_hash_ring.py`)
* MD5 of `"<node>_replica_<i>"` for `i < 500` positions every physical node 500 times on a 128-bit ring; a key is routed to the first position clockwise (`bisect_left`, wrap-around to index 0). MD5 is used as a fast, well-mixed, **deterministic** hash — not for security (`usedforsecurity=False`); Python's built-in `hash()` is salted per process and would route differently in every worker.
* Verified by tests: identical routing across processes with different `PYTHONHASHSEED`; insertion-order independence; adding a node only moves keys *to* the new node; removing and re-adding restores the original mapping; wrap-around.

## Measured properties (`benchmarks/simulations/`)
| Virtual nodes / node | Ownership of redis-a / b / c | Max deviation from 33.3 % |
|---|---|---|
| 150 | 39.65 / 28.64 / 31.71 % | 6.3 points |
| **500** | **33.86 / 34.58 / 31.57 %** | **1.8 points** |
| 1 000 | 33.38 / 32.51 / 34.11 % | 0.8 points |

Adding a 4th node moves **26.4 %** of 100 000 random keys (ideal 25 %), versus **75.3 %** for modulo hashing.

## What it does *not* do
* **Not a traffic balancer.** The ring balances *keys*. Under a Zipf workload one prefix can carry a quarter of all requests, and whichever node owns it carries that load (a synthetic Zipf(1.3) stream put ≈ 60 % of requests on one node while it owned 34 % of the keys). The remedies are a local L1 cache or hot-key replication; neither is implemented because no measurement shows the node is the bottleneck.
* **No membership management.** A failed node stays on the ring; requests that map to it are served as misses while its circuit breaker is open (see [ADR-004](./adrs/004-cache-failure-handling.md)). Removing it from the ring would remap its keys onto healthy nodes, trading cold misses for extra load on the survivors. That is an operator decision (change `REDIS_NODES`), not something the app does automatically — an earlier version of these docs claimed the opposite, which the failure tests disproved.
* **Naming matters.** Nodes are named `redis-a/b/c` only for `localhost:6379–6381`, otherwise `host:port`; renaming a node changes its ring positions and therefore remaps its keys. All API instances must use identical `REDIS_NODES` and `VIRTUAL_NODES`.
