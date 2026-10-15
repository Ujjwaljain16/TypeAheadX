# ADR-004: Cache failure handling — per-node circuit breaker, short timeouts, no client retries

**Date:** 2026-10-16
**Status:** Accepted (supersedes the implicit "catch the exception and treat it as a miss" behaviour)

## Problem
The read path is synchronous Python in a bounded thread pool (40 threads). With the original design ("on a Redis error, log and treat it as a miss") a single dead node among three took the *whole* API down: every request that hashed to that node blocked a thread on a 1 s socket timeout for the `GET` and again for the `SET`, and after ≈ 40 such requests the pool was exhausted — including requests that could have been answered from the two healthy nodes. Measured at 100 rps: **36–38 % errors and ≈ 17 s with zero successful requests**.

## Alternatives
1. Remove the dead node from the ring (membership management) — remaps a third of the keyspace onto the survivors, needs health checking and agreement between processes.
2. Shorter timeouts only — bounds each call but still pays it for every request.
3. **Per-node circuit breaker + short timeouts + no client retries** *(chosen)*.
4. Async Redis client — removes the thread-per-request cost but is a rewrite and does not address the "stop calling a dead dependency" problem by itself.

## Decision
* Each Redis node owns a circuit breaker (`utils/breaker.py`): the first failure opens it for 5 s (+0–20 % jitter so processes do not probe in lock-step); while open, operations on that node are skipped (a miss, no network I/O); then exactly one probe is allowed (half-open); success closes it.
* Socket and connect timeouts 250 ms (a miss costs ≈ 5 ms from PostgreSQL, so waiting longer for Redis is never worth it).
* **Client retries are disabled** (`Retry(NoBackoff(), 0)`). redis-py ≥ 6 retries failed commands 3× with exponential backoff by default; measured, that turns a 250 ms timeout into **7.6 s** against a black hole and 4.8 s against a refused port — it re-creates exactly the thread starvation the breaker removes. The first implementation of this ADR kept the default and still showed a 5 s stall at the moment of failure; only inspecting the outage timeline revealed it.
* The client is created lazily, so a node that is down at start-up is probed again later instead of being disabled for the process lifetime.
* Ring membership is **not** changed automatically.

## Consequences
**Positive:** one dead or frozen node costs one failed call, then zero I/O; measured at 100 rps with a node stopped or frozen for 20 s: 0 errors, p99 ≈ 9 ms (was 36–38 % errors). Invalidation also skips open nodes.
**Negative:** entries of a failed node are cold misses until it returns, and invalidations sent while a node is open are skipped — if the node was merely partitioned (data intact) stale entries survive until TTL.
**Neutral:** the breaker is per process; with N workers each discovers the failure independently (one failed call each).
**Verification:** `tests/test_cache_resilience.py` (dead node costs one call; single probe among 16 racing threads; failed probe re-opens; healthy nodes unaffected; failed call bounded < 1 s with a real black-holed socket), outage benchmarks (`docs/benchmark-details.md` §6), mutation checks M6/M10/M13.
