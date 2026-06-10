# TypeAheadX Architecture Reference

This document serves as the definitive technical reference for the TypeAheadX architecture. While the `README.md` documents the engineering journey, this file details the final system design, request lifecycles, and core algorithms.

---

## 1. System Overview

At a high level, TypeAheadX separates its read path and write path to optimize for conflicting requirements:
- **Reads** must be served in `< 50ms` to keep up with human typing speeds.
- **Writes** (user selections) happen in bursts and must not impact the read latency or overwhelm the database.

```text
                            +--------------------------+
                            |     Next.js Frontend     |
                            +-----------+--------------+
                                        |
                                        v
                            +--------------------------+
                            |        FastAPI           |
                            +-----------+--------------+
                                        |
                   +--------------------+--------------------+
                   |                                         |
            READ PATH                                  WRITE PATH
                   |                                         |
          +--------v---------+                      +--------v---------+
          | Distributed Cache|                      |   Write Buffer   |
          | (Consistent Hash)|                      | (In-Memory Map)  |
          +--------+---------+                      +--------+---------+
                   |                                         |
        +----------+----------+               [Flush @ 10s or 100 items]
        |          |          |                              |
 +------v---+ +----v-----+ +--v-------+              +-------v--------+
 | Redis A  | | Redis B  | | Redis C  |              | Async Aggregator|
 +------+---+ +----+-----+ +--+-------+              +-------+--------+
        |          |          |                              |
        |    [Cache Miss]     |                      [PostgreSQL UPSERT]
        +----------+----------+                              |
                   |                               [Invalidate Prefixes]
                   |                                         |
                   +--------------------+--------------------+
                                        |
                            +-----------v--------------+
                            |       PostgreSQL         |
                            +--------------------------+
```

---

## 2. Read Path Lifecycle

The Read Path is optimized entirely for speed, utilizing a cache-aside pattern shielded by consistent hashing.

**Scenario**: User types `"iph"`

```text
User types "iph"
       ↓
[Frontend]
Debounce (250ms) and request cancellation using AbortController
to prevent stale responses from racing with newer user input
       ↓
GET /suggest?q=iph
       ↓
[FastAPI]
       ↓
[Distributed Cache]
Compute MD5 Hash of "iph"
       ↓
[Hash Ring]
Bisect 500 Virtual Nodes to find physical owner
       ↓
[Redis Node] (e.g., redis-b)
```

**Outcome 1: Cache Hit**
- Redis returns the Top 10 JSON array.
- FastAPI returns response to user.

**Outcome 2: Cache Miss**
```text
[PostgreSQL]
Query B-Tree Index: 
SELECT query FROM queries 
WHERE query LIKE 'iph%' 
ORDER BY historical_count + (10.0 * recent_count) DESC 
LIMIT 10
       ↓
[FastAPI]
       ↓
Populate Cache (Redis SET)
       ↓
Return Response
```

---

## 3. Write Path Lifecycle

The Write Path is optimized for aggregation. Directly writing every user selection to the database would cause connection pool exhaustion during viral traffic events. 

**Scenario**: User clicks the suggestion `"iphone 15"`

```text
POST /search {"query": "iphone 15"}
       ↓
[FastAPI]
Return 200 OK immediately
       ↓
[Write Buffer]
In-memory aggregation (dict increment)
`buffer["iphone 15"] += 1`
       ↓
[Size/Time Trigger]
If buffer size >= 100 OR 10 seconds elapsed since last flush
       ↓
[Batch Worker]
Lock buffer, swap with empty dict, and process asynchronously
       ↓
[Trending Decay]
Calculate exponential decay for existing records
       ↓
[PostgreSQL UPSERT]
Single batch transaction: 
INSERT INTO queries ... ON CONFLICT DO UPDATE ...
       ↓
[Prefix Invalidation]
Identify all prefixes (e.g., "i", "ip", "iph", ...)
Delete them from the Distributed Cache
```

*Note: By invalidating prefixes on write, the next read path naturally rebuilds the cache with the freshest trends.*

---

## 4. Ranking Algorithm

TypeAheadX ranks queries using a composite score that balances all-time popularity against recent, viral trends.

**Core Formula:**
```math
final_score = historical_count + (10.0 × recent_count)
```

**Variables Explained:**
- `historical_count`: The absolute number of times the query has been searched historically.
- `recent_count`: A dedicated counter for recent traffic bursts.
- `β` (Beta Weight): A configurable multiplier (`10.0`) that amplifies the impact of recent searches.

**Exponential Decay:**
To ensure trends fade out when they are no longer relevant, we apply exponential decay to the `recent_count` during the batch flush process.
```python
hours_elapsed = (now - last_decay_at).total_seconds() / 3600
new_recent_count = old_recent_count * math.exp(-lambda * hours_elapsed) + new_searches
```
This guarantees that viral events spike the ranking quickly but decay organically over time without requiring heavy offline CRON jobs.

---

## 5. Cache Architecture

The caching layer is highly engineered to distribute traffic safely and efficiently.

- **Redis Nodes**: 3 independent Redis instances acting as key-value stores.
- **Consistent Hashing**: Instead of naive modulo hashing (`hash % N`), which invalidates ~75% of the cache when adding or removing a node, we map keys onto a 128-bit MD5 Hash Ring.
- **Virtual Nodes**: To prevent uneven traffic distribution, each physical Redis node is assigned **500 virtual nodes** scattered across the ring.
  - *Why 500?* Sensitivity studies proved that 150 virtual nodes yielded an unacceptable 10% ownership skew. 500 virtual nodes reduced the variance to `< 2%` with practically zero memory footprint.
- **Failure Behavior**: If a Redis node dies, its virtual nodes are removed from the ring. The `bisect` algorithm seamlessly routes traffic to the next closest healthy nodes.

---

## 6. Failure Modes

A production engineer must understand how the system breaks. Here is the known failure matrix:

| Failure Mode | Current Behavior | Production Solution |
| :--- | :--- | :--- |
| **Redis node dies** | **DB fallback**. The Hash Ring reroutes to healthy nodes, causing cache misses and spiking DB reads. | **Replication**. Use Redis Sentinel/Cluster with automatic failover to replica nodes. |
| **Cache stampede** | **DB overload**. 10,000 concurrent misses for the same key will query PostgreSQL 10,000 times. | **Singleflight**. Implement a locking mechanism (e.g., Go's `singleflight`) so only 1 request hits the DB. |
| **API crash** | **Lose buffer**. Any data sitting in the in-memory Write Buffer is lost on restart. | **Kafka**. Write events to a durable distributed log (Kafka) before aggregating. |
| **Hot key** | **Hot shard**. A viral prefix (e.g., "i") overloads a single physical Redis node regardless of hashing. | **Replication / Local Cache**. Replicate extremely hot keys across multiple shards or introduce an in-process LRU cache (L1). |

---

## 7. Known Production Limitations

| Limitation | Why it exists | Production solution |
| :--- | :--- | :--- |
| **Buffer data loss** | In-memory buffer is volatile | **Kafka durable log**. Write events to Kafka before aggregating. |
| **Hot key overload** | Consistent hashing balances keys, not traffic | **Hot key replication**. Replicate the hottest keys to all nodes dynamically. |
| **Cache stampede** | Concurrent misses hit DB | **Singleflight locking**. Implement in-memory request coalescing. |
| **Single region deployment** | No geographic redundancy | **Multi-region Redis/Postgres**. Use Global Datastore and read replicas. |
| **Manual cache topology** | Static Redis nodes configured via `.env` | **Service discovery**. Use Consul or etcd to map cluster membership dynamically. |
