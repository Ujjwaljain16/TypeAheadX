# Findings register

Baseline = commit `a45f129`. "Measured" = reproduced on the running system with the commands in
`REPRODUCING.md`; "Static" = read from code only (no execution evidence). Severity reflects impact on
users/operators if the system were deployed as documented, not on the demo.
Status values: **Fixed+verified** (regression test fails on old behaviour and passes now), **Fixed**
(change made, verification limited — stated), **Open** (not changed; reason given), **Doc**.

Regression-test column refers to files under `backend/tests/`. The mutation check
(`benchmarks/mutation_smoke.py`) re-introduces 12 of these defects into a copy of the code; all 12 are caught.

## Summary table

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
| F-10 | Medium | Documented trending ranking is not implemented; `idx_trending_score` is dead weight | measured | **Open** (product decision) |
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
| F-27 | Medium | No protection against a frozen (black-holed) database: requests hang | measured | **Open** (documented residual risk) |
| F-28 | Medium | Dependencies pinned to versions with 12 known vulnerabilities | measured (`pip-audit`) | Fixed+verified |
| F-29 | Low | Unknown/unset `CACHE_PROVIDER` silently falls back to an unbounded per-process in-memory cache | static | Open (documented) |
| F-30 | Info | `total_results` reports the number of returned rows (≤ 10), not matches | static | Doc |
| F-31 | Info | Cache-aside race window after invalidation (bounded by TTL) | static | Open (accepted, documented) |

---

## F-01 — Documented install does not produce a runnable app  *(High, confirmed)*
* **Evidence.** In a fresh venv, `pip install -r backend/requirements.txt` then `python -c "import app.main"`:
  `ModuleNotFoundError: No module named 'redis'` (`cache/redis_cache.py:4` imports it unconditionally from
  `cache/factory.py`). `requirements.txt` also lacks `httpx` (needed by `TestClient`); `requirements-lock.txt`
  is UTF-16 encoded, omits `redis`, and pins `starlette 1.2.1`, `anyio 4.13.0`, `urllib3 2.7.0`, `pydantic-settings 2.14.1`,
  `pytest 8.4.2` with 12 known advisories (see F-28). `scripts/*.py` additionally need `aiohttp`, `numpy` (listed nowhere).
* **Impact.** Nobody can start the service from the documented instructions; builds are not reproducible.
* **Fix.** `redis` added; `requirements-dev.txt` (pytest, pytest-cov, hypothesis, httpx); `benchmarks/requirements.txt`;
  lock regenerated from a clean environment (ASCII, 40 lines).
* **Verification.** Clean venv from `requirements-dev.txt`: 119/119 tests pass (also with pytest 9 and
  starlette 1.8 / FastAPI 0.143 / SQLAlchemy 2.1.4). Status: **Fixed+verified**.

## F-02 — LIKE metacharacters in user input  *(High, confirmed)*
* **Evidence.** `repositories/query_repository.py` baseline: `WHERE query LIKE :prefix || '%'` with the raw prefix.
  Measured on the baseline server: `q=%` and `q=_` return the global top-10 (`iphone 15 pro case`, …);
  `q=a_` returns `air fryer`, `airpods`, … (any 2-char prefix starting with `a`); `q=iphone%` matches
  `iphone …`; `q=\` returns `[]` (the backslash escaped the appended `%`). Also poisons the cache with keys such as `suggestion:%`.
* **Impact.** Wrong suggestions for any input containing `%`, `_`, `\` (e.g. "100%", "snake_case", Windows paths);
  trivially forces a scan-friendly "match everything" query (bounded by LIMIT, so not a DoS by itself).
  Not SQL injection: values are bound parameters (bandit: no B608 findings).
* **Fix.** `escape_like()` + `LIKE :pattern ESCAPE '\'`. EXPLAIN on a 60 000-row table confirms the
  `idx_query_prefix` index is still used (`test_prefix_query_uses_the_text_pattern_ops_index`).
* **Regression tests.** `test_repository_pg.py::test_prefix_matching_is_literal`, property test
  `test_like_pattern_equals_startswith_property` (150 generated cases against PostgreSQL),
  `test_api_integration.py::test_wildcard_characters_are_literal`. Mutant M2 is killed. **Fixed+verified.**

## F-03 — Cache invalidation never matches the cached keys  *(High, confirmed)*
* **Evidence.** Reads cache under `suggestion:<prefix>` (`suggestion_service.py`), the batch worker deletes `suggest:<prefix>`
  (`batch_worker.py:110`). Measured: `GET /suggest?q=zzq` → `[]` cached; five `POST /search zzqtest`; flush executed
  (`flushes_executed: 1`); `GET /suggest?q=zzq` still `[]` and `/cache/debug?prefix=zzq` reports `exists: true, ttl_seconds: 288`.
* **Impact.** "Active prefix invalidation" (README, `docs/cache-design.md` §3) does not exist; every write is invisible
  for up to `CACHE_TTL_SECONDS` (300 s) — i.e. the freshness guarantee the architecture is built around is false.
  Each flush also issued up to 64 `DEL`s per flushed query (≈ 1 600 for 100 queries) that could never hit a cached key — pure overhead (F-26).
* **Fix.** One key function (`services/normalization.suggestion_cache_key`) used by reads, invalidation and `/cache/debug`.
* **Regression tests.** `test_batch_worker.py::test_invalidation_deletes_exactly_the_keys_the_read_path_uses`,
  `test_api_integration.py::test_search_then_flush_makes_the_new_query_visible_despite_a_cached_empty_result`,
  `…::test_flush_updates_ranking_for_a_cached_prefix`. Mutant M1 is killed. **Fixed+verified.**

## F-04 — Read/write normalisation mismatch and unvalidated stored text  *(Medium, confirmed)*
* **Evidence.** Read: `" ".join(raw.strip().lower().split())`; write (`/search`): `strip().lower()` only. Measured:
  `POST /search "dbl  space   Test"` stored `dbl  space   test` (double spaces) — unreachable from `/suggest`, whose
  normaliser collapses spaces. No length limit, NUL, control-character or lone-surrogate check on the write path
  (NUL and surrogates cannot be stored by PostgreSQL → batch failure, F-05). Measured on the baseline: `GET /suggest?q=a%00b` → **HTTP 500**; `POST /search {"query":"a b"}` → 200 and the flush later fails silently (buffer emptied, `flushes_executed` unchanged). Unicode composed/decomposed forms (`é` vs `e◌́`) were different keys.
* **Fix.** `services/normalization.py` (NFC + lower + whitespace collapse) is the single normaliser; `validate_text` rejects empty
  (200 "ignored", API-compatible), > `MAX_QUERY_LENGTH` (200), control characters and lone surrogates (400).
* **Tests.** `test_normalization.py` (Hypothesis: idempotence, no edge/double whitespace, read==write), `test_api_integration.py`
  (`test_write_path_normalizes_like_the_read_path`, `test_write_path_rejects_unpersistable_queries`, surrogate via raw JSON). **Fixed+verified.**

## F-05 — A single bad row, or any DB error, discards the whole batch  *(High, confirmed)*
* **Evidence.** `BatchWorker.flush` swapped the buffer, then on any exception logged and dropped the snapshot ("accepted
  ephemeral data loss"). Measured: one incompressible 6 000-char query + 4 good queries in one batch →
  `index row size 6016 exceeds btree version 4 maximum 2704`; `/suggest?q=zzpoisongood` returned `[]` — all 5 events lost,
  `flushes_executed` unchanged, no metric records the failure. A transient connection error during a 10 s window loses the same way.
* **Impact.** Any unauthenticated client can erase other users' pending popularity updates; ordinary DB blips lose data silently.
* **Fix.** Validation (F-04); on failure: if the DB answers a ping, bisect the batch to isolate and drop only the unpersistable row(s)
  (counted in `events_dropped`); otherwise re-queue the uncommitted remainder (bounded by `WRITE_BUFFER_MAX_UNIQUE`); a commit is never followed by a
  re-queue (no double counting). New metrics: `flush_failures`, `events_requeued`, `events_dropped`, `last/max_flush_duration_ms`.
* **Tests.** `test_batch_worker.py` (7 cases incl. partial failure during bisect and re-queue overflow), `test_api_integration.py::test_incompressible_oversize_query_no_longer_poisons_the_batch`.
  Mutants M3, M4, M8 killed. **Fixed+verified.** Durability remains in-memory (see "Residual risks" in FINAL_REPORT).

## F-06 — Concurrent flushers lose updates  *(High, confirmed)*
* **Evidence.** `get_queries_by_names` (SELECT) → arithmetic in Python → `INSERT … ON CONFLICT DO UPDATE SET historical_count = EXCLUDED…`
  overwrites with a value computed from a stale read. `benchmarks/exp_lost_update.py`: 6 processes × 40 flushes × 3 events on one query,
  real PostgreSQL. Expected 720, **baseline stored 234 and 216 (67.5 % and 70.0 % lost)**, fixed code stored 720 (0 % lost).
* **Impact.** Any deployment with `--workers > 1` or several pods (which the docs recommend) systematically undercounts; also contradicts the advertised horizontal scaling.
* **Fix.** Atomic SQL merge (`historical_count = queries.historical_count + EXCLUDED…`, decay evaluated in SQL on the database clock);
  rows inserted in sorted order to avoid deadlocks; single statement via `unnest()` (O-6).
* **Tests.** `test_repository_pg.py::test_concurrent_flushers_do_not_lose_updates` (8 threads), `…::test_overlapping_batches_in_different_orders_do_not_deadlock`,
  `…::test_sql_decay_matches_reference_calculator`. Mutants M5, M9 killed. **Fixed+verified.**

## F-07 — Loss of one Redis node takes down the whole API  *(High, confirmed)*
* **Evidence.** `suggest` is a sync endpoint on a 40-thread pool; a request routed to a dead node blocks on `GET` and again on `SET`, and redis-py 8's
  **default retry policy** (3 retries, exponential backoff) multiplies each socket timeout — measured directly: a 250 ms timeout costs **7.6 s** against a
  black hole and **4.8 s** against a refused port (0.25 s with retries disabled). Baseline (1 s timeouts) therefore holds a thread for many seconds per request.
  Interleaved outage runs (100 rps warm cache, one of three nodes stopped/frozen from t = 15 s to 35 s, 2 reps each): **baseline 36–38 % errors, 16–17 s with
  zero successful requests, p99 ≈ 5 s**; fixed code 0 errors, 0 s without successes, p99 8.7 ms (stop) / 8.7–184 ms (pause). `BENCHMARK_RESULTS.md` §6.
  The design doc's claim ("virtual nodes … instantly deleted from the ring … system remains 100 % available") describes code that does not exist.
* **Impact.** A single cache-node failure is a complete outage at modest load although two thirds of the keyspace is healthy.
* **Fix.** Per-node circuit breaker (opens on one failure for 5 s ±20 %, a single half-open probe), 250 ms socket timeouts, **client retries disabled**
  (`Retry(NoBackoff(), 0)`), miss-on-skip, `delete_many` that skips open nodes, `breaker_skips` metric. *A first version of the fix kept the library's retries and still
  stalled for ~5 s at the transition; this was found only by inspecting the outage timeline and is now covered by a test and mutant M13.*
* **Tests.** `test_cache_resilience.py` (dead node costs one failed call then zero I/O, single probe under 16 racing threads, failed probe re-opens, healthy nodes unaffected,
  corrupt entry does not trip the breaker, real-socket black hole, failed call bounded < 1 s). Mutants M6, M10, M13 killed. **Fixed+verified.**
  Not covered: partial network partitions with asymmetric timing; real recovery of a restarted node under load beyond `exp_node_down_startup`.

## F-08 — Node down at start-up is never used again  *(Medium, confirmed)*
* **Evidence.** `RedisNode.__init__` sets `client = None` if the start-up `ping` fails; every method then returns early. `exp_node_down_startup.py`
  (redis-b stopped, API started, redis-b started, 150 requests for keys it owns): baseline redis-b `keyspace_hits` Δ0 and 0 keys stored;
  fixed code Δ100 hits and 50 keys.
* **Fix.** Lazy client + breaker (node is probed again after the window). **Fixed+verified** (`test_node_down_at_startup_recovers_…`).

## F-09 — Start-up cache warm-up always crashes  *(Medium, confirmed)*
* **Evidence.** `main.py:47` `QueryRepository()` without the required `session_factory`, `SuggestionService(repository, cache)` without
  required keyword args → `TypeError`, logged as "Task exception was never retrieved" at every start (seen in every baseline server log).
  The README's "Warming up cache for A-Z prefixes" never happened.
* **Fix.** Warm-up builds the service via `build_service`, runs in a worker thread, per-letter errors are logged. **Fixed+verified** (lifespan integration tests start it).

## F-10 — Documented ranking is not implemented  *(Medium, confirmed, Open)*
* **Evidence.** `docs/ARCHITECTURE.md` §4: `final_score = historical_count + 10·recent_count`. The only ranking query is
  `ORDER BY historical_count DESC, query ASC`; `recent_count` is written but never read for ranking; `TRENDING_BETA` is never read;
  `idx_trending_score` (3.2 MB) has `idx_scan = 0` and is maintained on every upsert. Because decay is applied only when a query is written,
  a stored `recent_count` of a query that is no longer searched never decays, so the indexed expression cannot rank "recent" correctly
  even if used — a correct implementation needs query-time decay (not indexable) or periodic decay.
* **Why open.** Changing ranking changes product behaviour (explicit rule 8). Options: (a) drop the dead index + document "popularity only"; (b) rank by a
  periodically-decayed score column; (c) rank by `historical + β·recent·exp(−λΔt)` computed over the top-K candidates only. Not changed.

## F-11 — Unauthenticated `/search`  *(Medium, confirmed; bounds fixed, authentication open)*
* **Evidence.** `/search` accepts arbitrary strings of any length with no authentication or rate limit. Baseline measurements: a single 50 MB request body was accepted
  (HTTP 200, server RSS +147 MB, queued as one 50 MB "query" that later poisons the flush); `exp_write_freeze.py` (PostgreSQL frozen for ≈ 2.5 min, 150 000 unique
  queries posted): the buffer grew without bound (149 492 entries, RSS 82 → 112 MB) — after the freeze everything was persisted (≈ 16 s), so this is a *memory-exhaustion*
  risk, not a data-loss one. Anyone can create suggestions (data poisoning) and inflate counts.
* **Fix.** 16 KiB body limit (413, also for chunked bodies), `MAX_QUERY_LENGTH`, buffer cap `WRITE_BUFFER_MAX_UNIQUE` = 50 000 (HTTP 503 + `Retry-After` when full, counted in
  `events_dropped`). Same experiment on the fixed code: 50 537 accepted, 99 463 rejected with 503, RSS 83 → 99 MB, every accepted event persisted.
* **Trade-off.** Under an extreme distinct-query flood the fixed service sheds events (explicitly) instead of buffering them.
* **Residual.** No authentication, per-client rate limiting or abuse filtering — requires gateway/product decisions.
  Tests: `test_oversized_request_body_is_rejected_before_being_buffered`, `test_write_buffer_is_bounded_and_reports_backpressure`. **Fixed (bounds) / Open (authentication).**

## F-12 — CORS `*` with credentials  *(Low, static, Fixed)*
`allow_origins=["*"]` + `allow_credentials=True` is invalid per the CORS spec and invites misconfiguration. Credentials are not used. Now
`allow_credentials=False`, origins configurable (`CORS_ORIGINS`). Test: `test_cors_has_no_credentials_with_wildcard_origin`.

## F-13 — Debug/metrics endpoints  *(Low, static)*
`/cache/debug`, `/cache/metrics`, `/metrics`, `/write/metrics` are unauthenticated and disclose ring topology (hashes, virtual-node names, TTLs); `/cache/debug` also performs
a Redis `GET` per call. With zero nodes `get_debug_info` returned a dict without the keys the route reads → HTTP 500. Fixed: `ENABLE_DEBUG_ENDPOINTS`
(default **true** to preserve behaviour — set false in production), empty-ring response, normalised key. Network-level access control remains the operator's job.

## F-14 — Compose exposes datastores to the network  *(Medium, static)*
`ports: "5433:5432"`, `"6379:6379"` … bind `0.0.0.0`; PostgreSQL password is `postgres`; Redis has no `requirepass`. Anyone on the LAN can read/modify
data or use Redis for code-execution gadgets. Fixed: bind to `127.0.0.1`. Passwords/TLS remain development defaults — not production-suitable.

## F-15 — `Settings()` constructed per request  *(Medium, profiled)*
`py-spy --gil` of the baseline serving 200 rps of cache hits: `get_settings` 21.5 % of GIL time (`pydantic_settings.__init__` 12.7 %, env/stat/dotenv parsing).
Fix: `lru_cache`. Measured effect in `OPTIMIZATIONS.md` O-1.

## F-16 — Database failure handling  *(Medium)*
SQLAlchemy errors surfaced as bare 500s; `pool_timeout` default 30 s; no connect timeout. Fixed: global handler → 503 + `Retry-After` (no message leakage —
`test_database_outage_maps_to_503_not_a_stack_trace`), `DB_POOL_TIMEOUT_SECONDS=5`, `DB_CONNECT_TIMEOUT_SECONDS=5`. Behaviour against a *frozen* database is F-27.

## F-17 / F-18 / F-19 / F-23 — smaller items
F-17: `CacheMetrics` used unsynchronised `+=` on class attributes from many threads (lost increments); now locked. Counters/buffers remain per process — with N workers,
`/metrics` reflects one arbitrary worker (documented). F-18: added `/ready` (DB ping → 503). F-19: `ingest.py` aborts (exit 1, "Ensure that no rows proposed for insertion within the same command have duplicate constrained values") when the CSV contains duplicate queries (verified with a 3-row CSV on the baseline) — now `GROUP BY query` with `SUM` (same CSV loads on the fixed script). F-23: `@app.on_event` and `setex` replaced by lifespan and `SET … EX`.

## F-20 — Frontend cannot be built on Linux  *(High, confirmed)*
`frontend/package.json` pins `next@16.3.0-preview.0` (no SWC binaries published: the fallback download returns 404) and works around it with a hard dependency on
`@next/swc-win32-x64-msvc`. In `node:22-alpine`: `npm ci` → `EBADPLATFORM … wanted {"os":"win32"} (current: linux)`. On Windows the build also warns about mismatching swc versions.
Fix: pin stable `next@16.2.7` / `eslint-config-next@16.2.7`, drop the Windows package. Verified: `npm ci` (366 packages), `tsc --noEmit` in the Linux container; `next build` and `tsc` on Windows.
(Linux `next build` itself was not run — `next/font/google` needs outbound network.)

## F-21 — Frontend behaviour  *(Medium, static + build verified)*
Verified correct: debounce (250 ms), abort of the previous request via a shared `AbortController`, `isMounted` guard against late results, keyboard navigation, `aria-*` combobox wiring.
Defects: `POST /search` used the hard-coded `http://localhost:8000` instead of `NEXT_PUBLIC_API_URL`; input had no `maxLength` (65+ chars → 400 "Bad Request" shown as error);
selecting a suggestion triggered a pointless suggest request for the selected text; `aria-autocomplete` missing; loading/error states not announced (no live region — open);
"No results" text shows the stale debounced term; page copy says "PHASE 2"; `<title>` is "Create Next App". Fixed: first four. There are **no frontend tests**; the cancellation/out-of-order
behaviour was verified by code inspection only (a browser E2E with a delayed backend was not run).

## F-22 — Claims not supported by code or methodology  *(Medium, documentation)*
See FINAL_REPORT §"Claims review" for the itemised list with evidence: "100,000 concurrent requests" are 1 000 closed-loop chunks of 100; the 97.29 % hit rate is an artefact of 10 000 synthetic keys that are not in the dataset (and the cap for a cold cache with that stream is 95.6 %); "node failure → vnodes deleted, 100 % available" is false (measured); the write-reduction figures come from an unseeded simulation that ignores the time trigger. **Verified as accurate:** the documented ring ownership (33.86/34.58/31.57 %), key movement on adding a node (26.4 %) and the ≈ 60 % request share of one node under the synthetic Zipf head (which is a workload property, as the docs say).

## F-24 — Process/tests  *(Info)*
Original suite: 5 tests, all needing a populated developer database, `TestClient` without lifespan, assertions that pass on empty results. Replaced/extended (119 tests, 90 % line coverage of `app/`,
mutation check 12/12). No CI configuration exists in the repository (not added: no hosting convention to follow); no application `Dockerfile` (container hardening could not be audited).

## F-25 — No coalescing of concurrent misses  *(Medium, measured)*
200 simultaneous requests for one uncached prefix (20 prefixes): baseline executed **3.5–10.1** prefix queries per prefix depending on session load (PostgreSQL statement log; 5 runs per session, 3 sessions), fixed exactly 1.0 in all 15 runs. Burst p50 ≈ 430 → ≈ 180 ms (headline matrix).
Per-process single-flight (`suggestion_service._single_flight`, double-checked, followers fall back to their own query on leader failure/timeout). Cross-process coalescing is not implemented (N workers ⇒ ≤ N queries per key).

## F-26 — Slow flush  *(Medium, measured)*
Flush of 100 distinct queries: ≈ 500 ms (SELECT + 100-row executemany + ≈ 1 600 sequential `DEL`s). Fixed ≈ 14 ms (O-5, O-6).

## F-27 — Frozen database  *(Medium, measured, Open)*
With `docker pause` on PostgreSQL the kernel keeps ACKing, so TCP-level timeouts never fire; statements on already-checked-out connections hang until the database resumes. Pool/connect timeouts bound *new* connection attempts only.
A real fix needs client-side per-request deadlines with connection invalidation (or an async driver with cancellation) — not attempted. Measured (60 rps, DB frozen 20 s, 2 reps): baseline 30 % errors / 16 s with zero successes, final 26 % / 13–14 s — **no meaningful improvement**. `BENCHMARK_RESULTS.md` §7.

## F-28 — Vulnerable pins  *(Medium)*
`pip-audit` on the original lock: `starlette 1.2.1` (PYSEC-2026-248/249), `anyio 4.13.0` (4024/4025), `urllib3 2.7.0` (4175-4177), `pydantic-settings 2.14.1` (CVE-2026-58203), `pytest 8.4.2` (1845) — 12 advisories.
New lock: "No known vulnerabilities found". The benchmark virtualenv deliberately stays on the old lock so baseline/final differ only in application code (stated in BENCHMARK_RESULTS).

## F-29 – F-31 — residual
F-29: any unknown `CACHE_PROVIDER` → per-process `InMemoryCache` with only a log warning; it has no size bound or eviction (memory grows with distinct prefixes). F-30: `total_results` = len(returned). F-31: after a flush invalidates a key, a reader that fetched from PostgreSQL *before* the commit can re-populate the key afterwards;
the stale entry lives ≤ TTL (300 s). Closing it needs versioned keys or write-through; judged disproportionate.
