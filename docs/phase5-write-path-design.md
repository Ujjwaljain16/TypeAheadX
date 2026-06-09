# Phase 5: Write Path Design

This document details the architectural decisions and components of the Write Path introduced in Phase 5 to support massive search ingestion and trending capabilities for TypeAheadX.

## The Problem
Handling high-throughput search queries directly to a database causes immense disk I/O, lock contention, and latency spikes. Furthermore, each incoming search query must update two competing signals:
1. **Historical Popularity:** The absolute count of how many times a query has ever been searched.
2. **Recent Trending Signal:** A recency-weighted score that favors fresh, viral trends.

## The Solution: Asynchronous Buffered Batch Writes

We have decoupled the fast API layer from the slow Storage layer using an asynchronous write buffer and an out-of-band mathematics engine.

### 1. In-Memory Write Buffer (`WriteBuffer`)
All incoming `POST /search` requests are immediately intercepted by an in-memory `WriteBuffer`. 
- **Thread-Safety:** Protected by a simple `threading.Lock`.
- **Complexity:** O(1) increment.
- **Client Latency:** Sub-millisecond. The API returns `200 OK` instantly.

### 2. Batch Worker (`BatchWorker`)
A daemon thread continuously monitors the `WriteBuffer`. A flush is triggered when either:
- **Size Trigger:** The buffer reaches 100 unique queries.
- **Time Trigger:** 10 seconds have elapsed since the last flush.

This dual-trigger prevents memory exhaustion during viral spikes while ensuring a bounded maximum staleness of 10 seconds during low traffic.

**Copy-on-Clear Optimization:**
When flushing, the worker briefly acquires the lock, makes a shallow copy of the dictionary, and clears the original. This allows the API to continue receiving requests unhindered while the slow database I/O happens in the background.

### 3. Trending Mathematics Layer (`TrendingCalculator`)
To adhere to the principle of Separation of Concerns, the database repository is strictly responsible for data persistence. All trending algorithms are encapsulated in the `TrendingCalculator` service.

During a flush, the worker:
1. Fetches the current database state for the snapshot's queries.
2. Passes both to the `TrendingCalculator`.
3. The calculator applies an Exponential Decay formula:
   `new_recent = old_recent * exp(-lambda * hours_elapsed) + delta`
4. The repository executes a single bulk UPSERT with the computed values.

### 4. Active Prefix Invalidation
After the DB is successfully updated, the cache must be made aware of the new ranking signals. Relying solely on a TTL would mean trending searches could be hidden behind stale cache entries for up to 5 minutes.
- The worker generates all possible prefixes for the updated queries.
- It deduplicates these prefixes using a `Set()`.
- It actively deletes these specific keys from the Distributed Cache.

## Schema Evolution
To support trending without storing every raw search event (which would require massive storage and batch processing), the `queries` table was migrated to include:
- `recent_count` (FLOAT)
- `last_decay_at` (TIMESTAMPTZ)
This allows us to maintain a continuous trending signal in just 3 columns per query.

## Failure Trade-offs
If the API process crashes ungracefully, any searches residing in the `WriteBuffer` that haven't been flushed will be lost. This is an explicit architectural trade-off. We accept a maximum data loss of 100 searches or 10 seconds of traffic to completely eliminate the need for a complex Write-Ahead Log (WAL) or message queue (e.g., Kafka) at this scale.
