# Architecture Deep Dive: Asynchronous Write Path & Trending Engine

This document provides a highly detailed architectural review of the TypeAheadX Write Path.

While the Read Path is optimized entirely for sub-millisecond latency via Consistent Hashing, the Write Path is designed as an **Asynchronous Shock Absorber**. Its primary job is to protect PostgreSQL from connection exhaustion during viral traffic events while continuously calculating exponential decay for trending queries.

---

## 1. The Core Problem: Write Saturation

When a user selects a suggestion, the frontend fires a `POST /search` event to update the query's popularity score.

If we naively executed a PostgreSQL `UPDATE` for every `POST` request, a viral news event (e.g., 50,000 users searching for `"celebrity news"`) would trigger 50,000 independent DB transactions. This would immediately exhaust the database connection pool, locking up the server and crashing the Fast Read Path.

---

## 2. The Solution: In-Memory Aggregation (The "Where" and "What")

We decoupled the API from PostgreSQL by introducing an asynchronous write buffer located at `backend/app/write_buffer/`.

### A. The In-Memory Map (`buffer.py`)
Instead of an array or message queue, the `WriteBuffer` is a simple Python dictionary: `dict[str, int]`.
- **Why?**: Search queries follow a strict Zipfian distribution. Highly popular terms are searched exponentially more often than tail queries.
- **The Compression**: If `"iphone"` is searched 10,000 times, the buffer simply increments the counter: `buffer["iphone"] += 1`. This naturally compresses 10,000 network requests into a **single** database row update. Our sensitivity studies (`scripts/write_sensitivity.py`) mathematically proved this achieves up to **95.37% write reduction** during viral spikes.
- **Concurrency**: The dictionary is protected by a fast `threading.Lock()` to handle concurrent FastAPI requests safely.

### B. The Batch Worker (`batch_worker.py`)
A background daemon thread continuously monitors the buffer. It flushes the buffer to the database based on two triggers:
- **Size Trigger**: `>= 100` unique items.
- **Time Trigger**: `10 seconds` since the last flush.

**The "Lock and Swap" Pattern:**
To ensure the background database I/O does not block incoming API requests, the worker executes a lightning-fast swap:
1. Acquire Lock.
2. Shallow copy the dictionary to a local variable.
3. Replace the active buffer with an empty dictionary.
4. Release Lock.
5. Spend the next several milliseconds/seconds executing slow DB I/O safely in the background.

---

## 3. The Trending Engine (`trending_calculator.py`)

Before writing to the database, we must calculate the true "Trending Score". 

We cannot run heavy offline CRON jobs to recalculate popularity. Instead, we use an **Inline Exponential Decay** algorithm.

When the worker flushes the buffer, it queries the database for the current state of those exact queries, then passes them to `TrendingCalculator`.

**The Math:**
```python
hours_elapsed = (now - last_decay_at).total_seconds() / 3600.0
new_recent_count = old_recent_count * math.exp(-0.5 * hours_elapsed) + new_searches
```
- **Why this works**: Older viral spikes decay gracefully over time. If a query hasn't been searched in 10 hours, its `recent_count` approaches zero. When a new search hits, we instantly update the decay and add the new traffic.
- **Efficiency**: We only ever calculate decay for queries that are *actively* being searched, avoiding the need for global table scans.

---

## 4. Bulk UPSERT & Active Invalidation

Once the new trending scores are calculated, the worker executes two final steps:

### A. PostgreSQL UPSERT (`query_repository.py`)
We map the decayed data into a single `INSERT ... ON CONFLICT DO UPDATE` statement. This ensures atomicity and requires only exactly one database transaction, regardless of how much traffic was absorbed.

### B. Active Cache Invalidation (`batch_worker.py`)
Because trending data has just changed in PostgreSQL, the Distributed Cache is now stale. 
1. The worker dynamically calculates all possible prefixes for the newly written queries (e.g., `"i"`, `"ip"`, `"iph"`).
2. It fires a `delete()` command to the Distributed Cache.
3. The very next user typing `"iph"` will experience a cache miss, forcing a fresh read from PostgreSQL that reflects the newly updated trending rankings.

---

## 5. Known Limitations

As documented in our Architecture review, this design accepts the following FAANG-scale trade-offs:
1. **Buffer Data Loss**: Because the buffer is an in-memory Python dictionary, if the FastAPI process crashes (OOM, Server Restart), any data sitting in the buffer for those 10 seconds is permanently lost.
   - **Production Solution**: Write events to a durable distributed log like **Kafka** *before* doing in-memory aggregation.
2. **Horizontal Scaling Challenges**: If we run 10 FastAPI pods, we have 10 separate in-memory buffers flushing to the DB.
   - **Production Solution**: Use a centralized streaming processor (like Flink or Spark Streaming) to aggregate across all API nodes.
