# Project Report: TypeAheadX Scalable Search Autocomplete System

## Disclaimer

This project was designed, implemented, tested, benchmarked, and documented by the authors. Large Language Models (LLMs) such as ChatGPT, Claude, and GitHub Copilot were used as productivity tools for brainstorming, refining documentation, improving code readability, generating diagrams, and polishing written content. All architectural decisions, implementation details, debugging, experiments, validations, and final design choices were performed and verified manually.

---

# 1. Introduction

Modern search systems rely heavily on autocomplete to improve user experience. A user expects suggestions to appear within a few milliseconds while typing, even when millions of users are querying the system simultaneously. Building such a system requires solving several conflicting problems:

* Fast read latency.
* Handling repeated requests efficiently.
* Avoiding database bottlenecks.
* Supporting trending queries.
* Scaling horizontally.
* Maintaining responsiveness during traffic spikes.

TypeAheadX was developed to explore these challenges and implement a production-inspired search architecture using FastAPI, PostgreSQL, Redis, and distributed systems principles.

The system evolved gradually from a simple database-backed autocomplete API into a horizontally scalable architecture with distributed caching, consistent hashing, asynchronous write buffering, and trending score computation.

---

# 2. System Architecture

TypeAheadX separates the read path and write path because both have different requirements.

* Reads must be extremely fast (<50 ms).
* Writes occur in bursts and should not affect read latency.

## High-Level Architecture

```text
                    +----------------------+
                    |   Next.js Frontend   |
                    +----------+-----------+
                               |
                               v
                     +-------------------+
                     |      FastAPI       |
                     +---------+----------+
                               |
              -----------------------------------
              |                                 |
          READ PATH                        WRITE PATH
              |                                 |
              v                                 v
     +------------------+             +------------------+
     | Distributed Cache|             |   Write Buffer   |
     | Consistent Hash  |             |  In-Memory Map   |
     +---------+--------+             +---------+--------+
               |                                |
      -------------------              Batch Flush Trigger
      |        |        |                       |
      v        v        v                       v
   Redis-A  Redis-B  Redis-C             Async Batch Worker
               |                                |
          Cache Miss                            |
               |                                |
               +--------------+----------------+
                              |
                              v
                     +------------------+
                     |   PostgreSQL DB   |
                     +------------------+
```

---

# 3. Dataset Source and Loading

## Dataset Used

AmazonQAC (Amazon Query AutoComplete Dataset)

Paper:
**AmazonQAC: A Large-Scale Naturalistic Query Autocomplete Dataset**
Authors: Dante Everaert et al.
Published at EMNLP 2024.

Original dataset size:
* 395 million search interactions.

For practical experimentation, a subset of 150,000 unique queries was selected.

### Stored Schema

The database schema includes tracking for historical popularity, recent trending metrics, and necessary indices for optimal prefix matching and score ranking:

```sql
CREATE TABLE IF NOT EXISTS queries (
    id BIGSERIAL PRIMARY KEY,
    query TEXT NOT NULL UNIQUE,
    historical_count BIGINT NOT NULL DEFAULT 0,
    recent_count FLOAT NOT NULL DEFAULT 0.0,
    last_decay_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_searched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_query_prefix
    ON queries (query text_pattern_ops);

CREATE INDEX IF NOT EXISTS idx_trending_score ON queries (
    (historical_count + 10.0 * recent_count) DESC
);
```

---

## Data Loading Procedure

1. Dataset downloaded from HuggingFace.
2. Preprocessing performed in Google Colab.
3. Duplicate queries aggregated.
4. Top 150,000 queries exported to: `queries.csv`

Columns:
```csv
query,historical_count
```

Imported using PostgreSQL `COPY` via the `ingest.py` script:
```sql
COPY queries_ingest_stage (query, historical_count) FROM STDIN WITH (FORMAT CSV)

INSERT INTO queries (query, historical_count)
SELECT query, historical_count
FROM queries_ingest_stage
ON CONFLICT (query)
DO UPDATE SET historical_count = queries.historical_count + EXCLUDED.historical_count;
```

---

# 4. API Documentation

## `GET /suggest`

Returns autocomplete suggestions based on both historical and trending scores.

**Request:**
```http
GET /suggest?q=iph
```
*(Note: The query parameter used in the codebase is `q` without an explicit `limit` parameter; the limit is handled via configuration settings.)*

**Response:**
```json
{
  "prefix": "iph",
  "total_results": 3,
  "suggestions": [
    {
      "query": "iphone",
      "historical_count": 15024
    },
    {
      "query": "iphone 16",
      "historical_count": 8432
    },
    {
      "query": "iphone charger",
      "historical_count": 4210
    }
  ]
}
```

---

## `POST /search`

Records user selection in the write buffer.

**Request:**
```json
{
    "query": "iphone 16"
}
```

**Response:**
```json
{
    "message": "Searched"
}
```

The request returns immediately while writes are buffered asynchronously.

---

## `GET /cache/debug`

Displays cache ownership information for the Consistent Hash ring.

**Request:**
```http
GET /cache/debug?prefix=iph
```

**Response:**
```json
{
    "prefix": "iph",
    "key": "suggestion:iph",
    "exists": true,
    "ttl_seconds": 298,
    "provider": "distributed_redis",
    "node": "redis-a",
    "hash": 184592,
    "virtual_node": "redis-a:781"
}
```

---

## `GET /metrics`

Provides unified cache and write-buffer statistics (implemented in `main.py`).

**Response:**
```json
{
  "cache": {
    "provider": "distributed_redis",
    "hits": 15200,
    "misses": 420,
    "sets": 420,
    "deletes": 0,
    "errors": 0,
    "hit_rate": 97.31,
    "node_hits": {
        "redis-a": 5100,
        "redis-b": 4900,
        "redis-c": 5200
    }
  },
  "write_buffer": {
    "searches_received": 100000,
    "flushes_executed": 258,
    "db_writes_executed": 25688,
    "db_writes_avoided": 74312,
    "write_reduction_percent": 74.31,
    "buffer_current_size": 42
  }
}
```

---

## `GET /write/metrics`

Returns specific write-buffer statistics.

**Response:**
```json
{
    "searches_received": 100000,
    "flushes_executed": 258,
    "db_writes_executed": 25688,
    "db_writes_avoided": 74312,
    "write_reduction_percent": 74.31,
    "buffer_current_size": 42
}
```

---

## `GET /health`

Health check endpoint.

**Response:**
```json
{
    "status": "healthy",
    "service": "typeaheadx-api",
    "phase": "phase-5"
}
```

---

# 5. Design Choices and Trade-offs

## Why PostgreSQL Instead of Trie?

Initially, a Trie-based design was considered. However, PostgreSQL's B-tree indexes already provide efficient prefix search while reducing application complexity.

**Trade-off:**
* **Advantages:** Simpler architecture, persistence handled automatically, easy debugging, and ACID compliance.
* **Disadvantages:** Cache misses depend on database latency.

---

## Why Redis Cache?

Repeated prefixes generate identical database queries.

Example:
```
iph
iphone
iphone 1
iphone 16
```
Without caching, PostgreSQL receives repeated reads for the same top-10 results. 
Redis Cache-Aside dramatically reduces database load by serving these repeated hot queries directly from memory.

---

## Why Consistent Hashing?

Modulo hashing causes cache avalanches when nodes are added or removed.
Consistent hashing minimizes key movement.

**Experiment (3 → 4 nodes):**
* Naive modulo: ~75% keys moved (invalidated).
* Consistent hashing: 26.44% keys moved.

---

## Virtual Node Tuning

Initial configuration: 150 virtual nodes
* Observed distribution: 39.6% / 28.7% / 31.7% (Unacceptable imbalance)

After experimentation: 500 virtual nodes (using an MD5 128-bit hash space)
* Distribution improved to: < 2% variance.

**Trade-off:** Slightly larger routing table in application memory in exchange for significantly better load balance.

---

## Why Batch Writes?

Writing every search immediately creates lock contention.

Instead:
* Buffer size = 100
* Flush interval = 10 seconds

**Benefits:**
* Reduces database writes.
* Smoothens traffic bursts.
* Supports trending updates.

**Trade-off:** Data present inside the buffer may be lost during sudden crashes before a flush can execute.

---

## Trending Engine

Ranking score:
```
score = historical_count + 10.0 * recent_count
```
*(As seen in `idx_trending_score` index).*

**Advantages:**
* Viral queries surface quickly.
* Trends disappear naturally over time without permanently polluting the historical dataset.

---

# 6. Performance Report

**Phase 1 Baseline**
* Architecture: `FastAPI → PostgreSQL`
* p50 latency: **7.48 ms**
* p95 latency: **9.95 ms**

**Phase 3 Cache Results**
* Database reads reduced by approximately **98%**.
* Cache hit rate: **97–98%**.

**Phase 4 Rebalancing Experiment (3 nodes → 4 nodes)**
* Naive modulo: **74.88%** cache invalidation
* Consistent hashing: **26.44%** key movement

**Phase 5 Write Buffer Results (100,000 search events)**
* Write reduction (Normal load): **74.31%**.
* Write reduction (Viral Zipfian workload): **95.37%**.

---

# 7. Limitations

Although TypeAheadX performs well, several limitations remain. As a production-style architecture, these limits were accepted to maintain scope:

1. **Thundering Herd:** Cache stampedes during node failure can overload PostgreSQL (requires singleflight request coalescing).
2. **Hot Keys:** Zipfian distribution means hot keys may overload individual Redis shards (consistent hashing distributes keys, not traffic).
3. **Volatility:** In-memory write buffer is not durable (requires Kafka/Redpanda).
4. **Availability:** Redis nodes lack replication (requires Redis Cluster / Sentinel).
5. **Geography:** Multi-region support is absent.

---

# 8. Conclusion

TypeAheadX evolved from a simple autocomplete API into a distributed search system incorporating caching, consistent hashing, write buffering, and trending analytics.

Throughout development, emphasis was placed not only on implementing algorithms but also on understanding their assumptions through experimentation and benchmarking.

One of the most important observations was that **balancing keys does not necessarily balance traffic.** Real-world workloads follow Zipfian distributions, and therefore system behavior is governed as much by workload characteristics as by algorithms themselves.

This project provided valuable exposure to backend engineering, caching strategies, distributed systems, workload modeling, and performance optimization principles commonly used in large-scale search infrastructure.
