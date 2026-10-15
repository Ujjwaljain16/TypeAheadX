# Write path

A user selecting a suggestion (`POST /search`) increments a popularity counter and feeds the trending signal. One `UPDATE` per click would turn a viral spike into thousands of transactions; instead the API aggregates in memory and a background thread writes in batches.

## Pipeline
1. **Ingest** — validate (≤ 200 chars, no control characters, normalised exactly like reads), then `WriteBuffer.increment(query)`: a lock-protected `dict[str, int]`. Returns immediately. The buffer holds at most `WRITE_BUFFER_MAX_UNIQUE` (50 000) *distinct* queries; counts for queries already present are always accepted; beyond the cap the API answers `503 + Retry-After` and counts `events_dropped`. Request bodies > 16 KiB are rejected with 413.
2. **Flush trigger** — checked every second: ≥ `WRITE_BUFFER_SIZE` (100) **distinct queries** (not events) or `WRITE_BUFFER_FLUSH_INTERVAL` (10 s) elapsed.
3. **Swap** — the buffer dict is replaced under the lock (copy-on-clear); ingest is never blocked by database I/O.
4. **Persist** — one SQL statement for the whole batch:
   `INSERT … SELECT FROM unnest(:queries, :deltas) ORDER BY q ON CONFLICT (query) DO UPDATE SET historical_count = queries.historical_count + EXCLUDED…, recent_count = queries.recent_count·e^(−λ·Δt) + EXCLUDED…`.
   The merge is evaluated by PostgreSQL under row locks and uses the database clock, so any number of API processes can flush concurrently without lost updates or clock skew (a read-modify-write version lost 67–70 % of updates with 6 flushers — see [lessons](./lessons-learned.md)). Rows are inserted in sorted order so overlapping batches lock in the same order.
5. **Invalidate** — after the commit, delete the cache keys of all prefixes of the flushed queries.

## Failure handling
| Case | Behaviour |
|---|---|
| database reachable, batch rejected (e.g. an unindexable row) | bisect the batch, persist everything else, drop and count only the offending row |
| database unreachable | the uncommitted remainder is merged back into the buffer (bounded) and retried on the next tick |
| commit succeeded, invalidation fails | never re-queued (that would double count); stale entries expire by TTL |
| graceful shutdown | final flush, also if the loop thread died |
| crash / `SIGKILL` | up to one flush window (≈ 10–11 s) of increments is lost |
| database frozen | the flush blocks (no deadline, by design — see [ADR-006](./adrs/006-write-path-durability-and-db-deadlines.md)); the buffer cap protects memory; events persist after recovery |

## What the numbers say
* Flush of 100 distinct queries: ≈ 500 ms originally (SELECT + 100 upserts + ≈ 1 600 sequential `DEL`) → **≈ 14 ms** (one statement, batched deletes).
* Write reduction depends on skew. A *simulation* (`benchmarks/simulations/write_sensitivity.py`: seeded, size-triggered only, counts rows) gives ≈ 63 % / 69 % / 95 % fewer row writes at buffer size 100 for Zipf α = 1.1 / 1.3 / 1.8, with diminishing returns for larger buffers at the price of staleness (a bigger buffer delays invalidation). Treat these as upper bounds for row writes; the real system issues one *statement* per flush regardless of size.

## Observability
`GET /write/metrics` and `/metrics`: `searches_received`, `flushes_executed`, `db_writes_executed/avoided`, `buffer_current_size`, `flush_failures`, `events_requeued`, `events_dropped`, `last/max_flush_duration_ms`.
