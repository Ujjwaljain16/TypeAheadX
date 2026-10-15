# Cache design

## Why cache at all
Typing "iphone" issues six requests (`i`, `ip`, `iph`, …), and short prefixes are shared by almost every user, so the same few thousand prefixes
account for most reads. A cache hit costs one Redis `GET` (≈ 0.3 ms) and no database work. In this project the database path is also fast (a miss is
≈ 4–6 ms end-to-end against ≈ 1–2 ms for a hit), so the cache's job is less "make it fast" than **make it cheap and make it survive load**: CPU per request
is lower on hits, and the database never sees the popular prefixes.

## Pattern: cache-aside, one JSON document per prefix
* Key `suggestion:<normalised prefix>` (single function `services.normalization.suggestion_cache_key`, shared by reads, invalidation and the debug endpoint — a mismatch between the read and the invalidation key once made invalidation a silent no-op, see [lessons](./lessons-learned.md)).
* Value: the complete response body (`{"prefix": …, "total_results": …, "suggestions": [...]}`), served verbatim on a hit. Entries that do not look like a response document are treated as misses.
* TTL 300 s; empty results are cached as well (negative caching).
* Only the default `LIMIT` is cached (the key does not encode the limit).

## Misses
* **Single-flight:** concurrent misses for a key share one database query (leader/follower; followers wait ≤ 5 s and fall back to their own query if the leader fails). Measured: 200 simultaneous misses → exactly 1 query, versus 3.5–10 without it.
* **Database guard:** misses go through a deadline (2 s), a concurrency limit (15) and a circuit breaker — see [ADR-006](./adrs/006-write-path-durability-and-db-deadlines.md).

## Invalidation
After each flush, every prefix (up to 64 characters) of every flushed query is deleted, grouped by owning node, ≤ 100 keys per `DEL` (measured: a single 500-key `DEL` stalled ≈ 95 ms on the test platform, 100-key chunks take ≈ 2 ms per 600 keys). 100 flushed queries ≈ 1 600 keys ≈ 2–7 ms.
Invalidation is best-effort: an unreachable node is skipped (its entries expire by TTL).

## Failure semantics
A Redis problem is never a request error — the cache returns "miss" and the request is answered from PostgreSQL. Each node has its own circuit breaker
([ADR-004](./adrs/004-cache-failure-handling.md)). Metrics (`/cache/metrics`): hits, misses, sets, deletes, errors, `breaker_skips`, per-node hits.

## Known limitations
* Staleness ≤ TTL (300 s) in the invalidation race (reader fetched before the commit, stored after the delete).
* `noeviction` / no `maxmemory` in the compose file: size Redis for the distinct-prefix cardinality (≈ 540–700 B per entry measured) or set an LRU policy.
* Counters and breakers are per process.
