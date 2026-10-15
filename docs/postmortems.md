# Post-mortems: ten things that were wrong, and what each taught

The project began as a prototype that *described* a lot of good engineering (active cache invalidation, node-failure tolerance, horizontally scalable writes, trending ranking). I then tried to break each claim at runtime, against a real PostgreSQL and real Redis. Ten failures were instructive enough to write up properly; the rest are in the table at the bottom. Each entry follows the same shape: **symptom → root cause → how it was found → fix → trade-off → lesson.** The generalised takeaways are in [`lessons-learned.md`](./lessons-learned.md); the measurements behind the numbers are in [`benchmark-details.md`](./benchmark-details.md). IDs (F-xx) are stable references used elsewhere in the docs.

---

## 1. "Active invalidation" that never invalidated  (F-03)
* **Symptom.** `GET /suggest?q=zzq` → `[]` (cached). Five `POST /search zzqtest`, a flush, `GET` again → still `[]`; the debug endpoint showed the key alive with 288 s of TTL left. The architecture's central freshness mechanism did nothing.
* **Root cause.** Reads cached under `suggestion:<prefix>`; the batch worker deleted `suggest:<prefix>`. Two hand-written strings.
* **Found by** the simplest end-to-end test imaginable: write → flush → read.
* **Fix.** One function builds the key; reads, invalidation and the debug endpoint all call it. Invalidation is also batched per node now.
* **Trade-off.** Invalidation is still best-effort: a reader that loaded from PostgreSQL *before* the commit can re-populate a key after the delete; that entry lives ≤ TTL (300 s). Closing it needs versioned keys or write-through — judged disproportionate.
* **Lesson.** Derive anything two components must agree on from one definition, and test the *loop*, not the pieces.

## 2. One dead Redis node took the whole API down  (F-07)
* **Symptom.** At 100 rps, stopping one of three Redis containers: **36–38 % errors, ~17 s with zero successful requests** — although two thirds of the keys lived on healthy nodes.
* **Root cause.** The endpoint is synchronous in a 40-thread pool. Each request routed to the dead node blocked a thread on its socket timeout for the `GET` and again for the `SET`; after ~40 such requests nothing could be served, cached or not. "Treat Redis errors as a miss" is correct per request and wrong in aggregate.
* **Found by** the `outage` scenario with a per-second timeline.
* **Fix v1.** Per-node circuit breaker (open 5 s after a failure, one half-open probe), 250 ms timeouts, lazy client. Better — but the timeline still showed a **5 s stall at the moment of failure**.
* **Fix v2 (the real root cause).** redis-py ≥ 6 *retries failed commands three times with exponential backoff by default*: a 250 ms timeout cost **7.6 s** against a black hole and 4.8 s against a refused port. Retries are now disabled; the breaker is the retry policy. Result: 0 errors, p99 ≈ 9 ms, no unavailable second.
* **Trade-off.** A failed node's keys are cold misses (PostgreSQL absorbs them); invalidations sent while its breaker is open are skipped, so a node that was merely partitioned can keep stale entries until TTL. Ring membership is *not* changed automatically — that remaps a third of the keyspace and is an operator decision.
* **Lesson.** Degrade by *not calling* the dependency, bound every wait, read the effective retry policy of every client, and examine the transition, not just the steady state.

## 3. Concurrent flushers lost two thirds of the updates  (F-06)
* **Symptom.** 6 processes × 40 flushes of 3 increments on one query: expected 720, stored **234 and 216 (67.5 % / 70.0 % lost)**. Zero with one process.
* **Root cause.** `SELECT` the row → add in Python → `UPSERT` the computed value: a classic lost update, invisible with a single worker.
* **Fix.** The merge happens in SQL under the row lock: `historical_count = queries.historical_count + EXCLUDED.historical_count`, decay computed on the database clock (no cross-host clock skew), rows inserted in sorted order so overlapping batches cannot deadlock, all in **one** `INSERT … SELECT FROM unnest(…)` statement (flush of 100 queries: ≈ 500 ms → ≈ 14 ms).
* **Trade-off.** The decay formula now lives in SQL *and* in the reference Python class used by the tests; a test pins them to each other.
* **Lesson.** If more than one process can write, a read-modify-write in application code is a bug. Push the merge into the database and make lock order deterministic.

## 4. One bad row erased everyone's events  (F-05, F-04)
* **Symptom.** A 6 000-character random query plus four good ones in a batch: PostgreSQL rejected the index entry (`index row size exceeds btree maximum`), the code logged one line and dropped the whole snapshot — five events lost, no metric. Any unauthenticated client could do this to other users' pending updates.
* **Root cause.** "Accepted ephemeral data loss" had been applied to *all* failures, including data-dependent ones, and the write path validated nothing the read path validated.
* **Fix.** A single normaliser/validator for reads, writes, cache keys and invalidation. On failure: if the database answers a ping the batch is **bisected** to isolate and drop only the unpersistable row; if it does not, the uncommitted remainder is **re-queued** (bounded) — and a committed batch is never re-queued, so nothing is double counted.
* **Trade-off.** Valid-looking input is rejected earlier (400); the buffer is bounded (50 000 distinct queries) so extreme floods get explicit `503 + Retry-After`.
* **Lesson.** Classify failures (transient vs. data-dependent) before choosing "retry", "drop" or "isolate"; validate once, centrally.

## 5. A frozen database starved the whole service  (F-27)
* **Symptom.** `docker pause` on PostgreSQL for 20 s: **14 s with zero successful requests**, requests hanging ≈ 6 s — including requests that were in the cache.
* **Root cause.** Sync driver calls cannot be interrupted client-side; when a server freezes the kernel still ACKs, so no TCP timeout ever fires. Every cache miss holds a request thread, and 40 of them end the service.
* **Fix.** Reads go through a **deadline (2 s) + bulkhead (≤ 15 calls, 50 ms wait for a slot) + circuit breaker**; misses then fail instantly with `503 + Retry-After` while cache hits keep being served. Result: **0 unavailable seconds, slowest request 2.0 s, p99 12–18 ms**. Cost when healthy: ≈ +0.4 ms on the miss path (one thread hop).
* **Deliberately not guarded: writes.** A timed-out write may still execute later, so retrying or re-queueing it would double count. Writes keep their blocking, at-most-once behaviour; the bounded buffer protects memory. A deadline for writes needs an idempotency key ([ADR-006](./adrs/006-write-path-durability-and-db-deadlines.md)).
* **A regression I introduced and then measured away.** The first guard rejected instantly at 12 slots and let saturation open the breaker; under short stalls it produced occasional 503s (3 of 6 runs). Raising the limit to the pool size, waiting ≤ 50 ms for a slot, and making saturation *not* trip the breaker removed them (0 of 4 runs).
* **Lesson.** A timeout you cannot enforce is not a timeout. Decide per operation whether abandoning it is safe — and measure the safeguard's own cost and failure modes.

## 6. The "trending" feature that didn't trend  (F-10)
* **Symptom.** The docs ranked by `historical + 10·recent`; the SQL ordered by `historical_count` only. `recent_count` was written and never read; the supporting index had zero scans.
* **Root cause.** Half-implemented. And even wired up, a *stored* decayed value only decays when the row is written, so a query that went viral yesterday and was never searched again would stay boosted forever.
* **Fix.** Evaluate the decay **at read time**: `score = historical + β·recent·e^(−λ·hours since update)`. Rows never searched through `/search` sort exactly as before; the unusable index is gone ([ADR-005](./adrs/005-read-time-trending-ranking.md)). Verified end-to-end: 120 searches make a 227-count query rank first (count 347 < 987); with no new write it falls back as the decay proceeds.
* **Trade-off.** The score is computed for every row matching the prefix: worst case (1-char prefix, 6 177 rows) +0.8 ms; typical prefixes unchanged; results are cached so a trend appears after the next invalidation.
* **Lesson.** Time-decayed values must be decayed where they are *read*; test that a feature changes observable behaviour, not that its code exists.

## 7. `%` and `_` in a search box  (F-02)
* **Symptom.** `q=%` returned the global top-10, `q=a_` matched every two-character prefix starting with `a`, `q=\` returned nothing. Also poisoned the cache with keys like `suggestion:%`.
* **Root cause.** User input concatenated into a `LIKE` pattern. Not SQL injection (values were bound parameters) — a *semantic* injection.
* **Fix.** Escape `\`, `%`, `_` and use `LIKE :pattern ESCAPE '\'`; a test asserts the `text_pattern_ops` index is still used (no sequential scan on a 60 000-row table), and a property test checks 150 generated patterns against PostgreSQL.
* **Lesson.** Bound parameters protect the SQL, not the *meaning* of the value. Add property tests for escaping.

## 8. An unauthenticated endpoint that trusted everyone  (F-11)
* **Symptom.** A single 50 MB `POST /search` was accepted (HTTP 200, +147 MB server memory, queued as one 50 MB "query"); the write buffer grew without bound while the database was frozen (82 → 112 MB for 150 000 unique strings).
* **Fix.** 16 KiB body limit (also for chunked bodies), 200-char query limit, 50 000-distinct buffer cap with explicit 503 backpressure. Same experiment afterwards: 83 → 99 MB, every accepted event persisted.
* **Trade-off.** Under an extreme flood the service now *sheds* new distinct queries instead of buffering without limit.
* **Still open.** No authentication or rate limiting — anyone can inject suggestions. That needs a gateway/product decision.
* **Lesson.** Every structure that user input can grow needs a bound and an explicit overflow behaviour.

## 9. The frontend that only built on Windows  (F-20)
* **Symptom.** `npm ci` in `node:22-alpine` → `EBADPLATFORM … @next/swc-win32-x64-msvc`.
* **Root cause.** The project pinned a *preview* Next.js build that had no published native binaries, and worked around it with a Windows-only hard dependency.
* **Fix.** Pin a published release (16.2.7); `npm ci`, type-check and build now run on Linux in CI.
* **Lesson.** If CI cannot build it from a clean checkout, it does not build.

## 10. Measuring the system without fooling myself
This one is about the instruments, not the product — and it shaped every number above.
* **Closed vs open loop.** The original benchmark sent chunks of 100 and waited — "100 000 concurrent requests" never exceeded 100 in flight, and a slow server simply received fewer requests. The new generator schedules arrivals at a fixed rate and measures latency from the *intended* send time.
* **The generator was lying.** `asyncio.sleep(1 ms)` took 12–15 ms on Windows (power-throttled timer), inflating every latency by up to 15 ms; a `psutil` call holding the GIL added jitter; the fix (spin before each send, persistent connections, recorded dispatch lag) was found by calibrating against `/health`.
* **The machine drifts.** The identical baseline code measured 3.5–4 ms p50 in one hour and 1.8–2 ms two hours later, with a "knee" at 300 rps vs 650 rps. Every headline comparison is therefore *interleaved* (A, B, A, B…).
* **A result that told me what I expected.** I once "found" 99 % data loss during a database freeze; the drain check was reading the wrong signal. The corrected experiment showed *no* loss (the real problem was unbounded memory). I deleted the claim.
* **Lesson.** Calibrate the instrument, replicate, interleave, and distrust the result that confirms your hypothesis too neatly.

---

## All findings at a glance
| ID | Sev | Title | Evidence | Status |
|---|---|---|---|---|
| F-01 | High | Documented install does not produce a runnable app; lock file stale/vulnerable | measured | Fixed+verified |
| F-02 | High | `LIKE` metacharacters in user input change query semantics | measured | Fixed+verified |
| F-03 | High | Cache invalidation uses a different key than the read path — never works | measured | Fixed+verified |
| F-04 | Medium | Write path and read path normalise differently; no validation of stored text | measured | Fixed+verified |
| F-05 | High | One bad row (or any DB error) silently discards the whole write batch | measured | Fixed+verified |
| F-06 | High | Concurrent flushers lose 67–70 % of updates (read-modify-write) | measured | Fixed+verified |
| F-07 | High | Loss of one Redis node takes down the whole API | measured | Fixed+verified |
| F-08 | Medium | A Redis node that is down at start-up is never used again | measured | Fixed+verified |
| F-09 | Medium | Start-up cache warm-up always crashes | measured | Fixed+verified |
| F-10 | Medium | Documented trending ranking was not implemented; `idx_trending_score` was dead weight | measured | Fixed+verified (follow-up commit) |
| F-11 | Medium | Unauthenticated `/search`: unbounded buffer, 50 MB bodies, data poisoning | measured | Fixed (bounds) / Open (auth) |
| F-12 | Low | CORS `*` combined with `allow_credentials=True` | static | Fixed |
| F-13 | Low | Unauthenticated debug/metrics endpoints; `/cache/debug` 500 with empty ring | static | Fixed (toggle, default on) / Open |
| F-14 | Medium | `docker-compose.yml` publishes PostgreSQL (postgres/postgres) and 3 unauthenticated Redis on all interfaces | static | Fixed |
| F-15 | Medium | `Settings()` rebuilt (re-parses `.env`) on every request: 21.5 % of hit-path CPU | profiled | Fixed+measured |
| F-16 | Medium | DB failures surface as raw 500s; 30 s pool wait; no connect timeout | measured | Fixed (partially verified) |
| F-17 | Low | Metrics counters racy and per-process | static | Fixed (thread-safe) / Doc (per-process) |
| F-18 | Low | `/health` is not dependency aware | static | Fixed (`/ready` added) |
| F-19 | Low | `ingest.py` aborts on duplicate keys within one load | static | Fixed |
| F-20 | High | Frontend cannot be installed/built on Linux (hard Windows-only dependency, preview Next pin) | measured | Fixed+verified |
| F-21 | Medium | Frontend: hard-coded `/search` URL, unbounded input, wasted refetch after selection, a11y gaps | static | Fixed (partially) |
| F-22 | Medium | Documentation and benchmark claims not supported by the code or by the methodology | measured/static | Doc (see FINAL_REPORT) |
| F-23 | Low | Deprecated APIs (`on_event`, `setex`) | static | Fixed |
| F-24 | Info | No CI, no application Dockerfile, no lint config; original tests non-hermetic and vacuous | static | Partially addressed |
| F-25 | Medium | Concurrent identical cache misses are not coalesced (3.5–10 DB queries per key for 200 simultaneous requests) | measured | Fixed+measured |
| F-26 | Medium | Cache invalidation and flush are slow (≈ 0.5 s per 100 queries) because of per-key round trips | measured | Fixed+measured |
| F-27 | Medium | No protection against a frozen (black-holed) database: requests hang | measured | Fixed for reads (follow-up commit) / writes deliberately unchanged |
| F-28 | Medium | Dependencies pinned to versions with 12 known vulnerabilities | measured (`pip-audit`) | Fixed+verified |
| F-29 | Low | Unknown/unset `CACHE_PROVIDER` silently falls back to an unbounded per-process in-memory cache | static | Open (documented) |
| F-30 | Info | `total_results` reports the number of returned rows (≤ 10), not matches | static | Doc |
| F-31 | Info | Cache-aside race window after invalidation (bounded by TTL) | static | Open (accepted, documented) |
