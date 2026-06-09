# Phase 3: Cache Design Architecture

## Overview
Phase 3 transitions the application from a read-heavy direct-to-database API into a resilient distributed system using the **Cache-Aside** pattern.

## Architectural Decisions

**Why Cache?**
In Phase 2, we learned that debouncing successfully reduces requests *per user*. However, globally, users still search for the exact same "hot prefixes" (like `iph`, `iphone`, `samsung`). Without a cache, 10,000 distinct users searching for `iphone` triggers 10,000 identical database reads. Caching solves population-level redundancy.

**Why Redis?**
Redis is an extremely fast, single-threaded in-memory key-value store. It supports native TTLs, data structures, and persistent backing. Crucially, it sets the foundation for Phase 4 where we can shard keys across multiple Redis nodes.

**Why Cache-Aside?**
Cache-Aside gives the application full control over the data retrieval flow. If the data is missing from the cache, the application fetches it from the database and updates the cache. This prevents the cache from needing to know how to connect to or query PostgreSQL, maintaining clean domain boundaries.

**Why 5 Minute TTL?**
A 300-second TTL guarantees that edge nodes hold onto sub-millisecond responses long enough to absorb traffic spikes, but short enough that when new products begin trending (e.g., a new iPhone release), the edge cache automatically invalidates and fetches the updated search suggestions.

**Why CacheFactory?**
The `CacheFactory` pattern abstracts away the storage engine. The application business logic (`SuggestionService`) only talks to a `CacheInterface`. If we want to pivot to Memcached, DynamoDB, or a custom distributed hash ring in Phase 4, we only modify the factory—the service layer remains untouched.

**Why Graceful Degradation?**
A cache is an optimization layer, not a source of truth. If Redis goes offline, the application catches the error, logs it, increments `cache_errors`, and silently queries PostgreSQL. Users experience slightly higher latency instead of a 500 Internal Server Error.

## The Keyspace Design
Keys are strictly namespaced to prevent collisions across different data types:
```
suggestion:iph
suggestion:iphone
```
If we later add trending queries or user histories, we can easily isolate them (e.g., `trending:daily`, `user:123:history`).

## Metrics & Observability
We added native tracking inside the singleton `CacheMetrics`.

Available via `GET /cache/metrics`:
- **hits**: Number of successful cache reads.
- **misses**: Number of cache misses (triggers DB read).
- **sets**: Number of successful cache writes.
- **deletes**: Number of cache invalidations.
- **errors**: Network or availability errors from the cache provider.
- **hit_rate**: `(hits / (hits + misses)) * 100`
