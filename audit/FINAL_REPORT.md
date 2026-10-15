# TypeAheadX — Final audit report

Baseline: commit `a45f129`. Audited tree: the working directory (uncommitted; see `git status`).
Companion documents: `FINDINGS.md` (31 findings), `ARCHITECTURE.md`, `BENCHMARK_RESULTS.md`, `CAPACITY_AND_LIMITS.md`,
`OPTIMIZATIONS.md`, `REPRODUCING.md`; code in `benchmarks/`, tests in `backend/tests/`, raw data in `audit/results/`.

## 1. Overall assessment

TypeAheadX is a clean, readable ~1 300-line prototype whose *ideas* are sound (cache-aside, consistent-hash ring, buffered writes,
text_pattern_ops prefix index). Its *engineering claims* were largely ahead of its implementation. The audit found,
reproduced and fixed several defects that silently negated headline features, and measured one that turns a routine cache-node
failure into a total outage:

| What the docs promise | What the baseline actually did (measured) |
|---|---|
| "Active prefix invalidation keeps trending fresh" | Invalidation used a different key than reads — it **never** matched; writes were invisible for up to 300 s (F-03) |
| "Cache node failure → 100 % available, vnodes removed from ring" | **No** ring removal exists; at 100 rps one dead node ⇒ **36–38 % errors and ~17 s with zero successful requests** (F-07) |
| "Horizontally scalable" write path | 6 concurrent flushers lost **67–70 %** of counter updates (read-modify-write) (F-06) |
| "Write buffer protects the DB" | One unpersistable row discarded the whole batch; no failure metric; unbounded memory; 50 MB bodies accepted (F-05, F-11) |
| Trending ranking = history + 10·recent | Ranking uses `historical_count` only; the trending index is dead weight (F-10, **left open**) |
| Install & run from README | `import app.main` fails in a clean env (`redis` missing); frontend cannot be built on Linux (F-01, F-20) |

After the changes the system is **materially more correct, more resilient and cheaper per request**, but it is **not production-ready**:
it still has no authentication/rate limiting, no durable event log, no protection against a hung database, an unverified
multi-worker/Linux behaviour, no CI, and the documented trending ranking remains unimplemented.

## 2. Verified architecture (summary; details in `ARCHITECTURE.md`)
Browser (debounce 250 ms, abort-previous) → FastAPI sync `/suggest` (thread pool) → normalise → Redis ring (MD5, 500 vnodes, 3 nodes) → on miss PostgreSQL
`LIKE 'prefix%'` ordered by `historical_count` → cache 300 s. `/search` → in-process dict → daemon thread flushes every 10 s or 100 distinct queries → SQL upsert → cache invalidation.
Verified against code, not docs; discrepancies are listed in §6.

## 3. Critical findings and their resolution
| ID | Finding | Resolution | Verified by |
|---|---|---|---|
| F-07 | one Redis node down ⇒ full outage (thread starvation + redis-py default retries 3× backoff ⇒ 250 ms timeout = 5–8 s) | breaker + short timeouts + **retries disabled** | interleaved outage runs: errors 37 % → 0 %, zero-success seconds 17 → 0; unit + real-socket tests |
| F-06 | concurrent flushers lose updates | atomic SQL merge, ordered rows | 70 % → 0 % loss experiment; concurrency tests |
| F-03 | invalidation key mismatch | single key function | unit + integration regression, mutation M1 |
| F-05 | batch poisoning / silent loss | validation, bisect-isolation, re-queue, metrics | 7 unit + integration tests |
| F-02 | LIKE metacharacters | escaping, `ESCAPE '\'`, index use asserted | 150-case property test vs PostgreSQL |
| F-20, F-01 | cannot install/build | requirements, lock regenerated (0 CVEs), Next pinned to a published release | clean-venv 121/121; Linux `npm ci` + `tsc` |
| F-10 | trending ranking not implemented | **not changed** (needs product decision; options in FINDINGS) | — |
| F-27 | hung (frozen) PostgreSQL | **not fixed**; measured: no improvement (26 % vs 30 % errors) | `BENCHMARK_RESULTS.md` §7 |

## 4. Security assessment (threat model summary)
Assets: suggestion integrity (popularity counters), availability, Redis/PostgreSQL data. Trust boundary: the public HTTP API (anyone can call `/search`, `/suggest`, `/metrics`, `/cache/*`).
Attackers: anonymous remote client; an attacker on the Docker host's network (compose published datastores on `0.0.0.0` with default credentials).

| Scenario | Baseline | Now | Residual |
|---|---|---|---|
| SQL injection | none found (bound parameters; bandit clean); `%`/`_` semantic injection (F-02) | fixed | — |
| Memory/CPU DoS via `/search` (huge body, unique flood) | 50 MB accepted (+147 MB RSS); unbounded buffer | 16 KiB limit (413), 200-char limit, 50 000-distinct cap with 503 | no rate limit/auth: a client can still fill the cap and shed others' events |
| Data poisoning | unauthenticated | unchanged | needs auth/abuse controls (product) |
| Batch poisoning | one row erased everyone's events | isolated | — |
| Datastore exposure | `0.0.0.0` + `postgres/postgres`, Redis no auth | loopback only (dev) | no passwords/TLS/ACLs — dev defaults |
| Information disclosure | raw 500s; ring internals via `/cache/debug` | 503 w/o detail; `ENABLE_DEBUG_ENDPOINTS` toggle (default **on** for compatibility) | set false in production; put metrics behind the network boundary |
| CORS | `*` + credentials | `*`, no credentials, configurable | — |
| Dependencies | 12 advisories in the lock | 0 in the new lock; benchmark venv deliberately unchanged | apply new lock in deployments |
| Containers | no app Dockerfile (cannot assess) | — | non-root, read-only FS, limits: unassessed |

Log injection: queries are logged only on failure and truncated to 40 chars with `%r`. Cross-user leakage: not applicable (no user data). Security headers (HSTS, CSP, etc.): none set — deployment-layer concern, not added.

## 5. Results (details and uncertainty in `BENCHMARK_RESULTS.md`)
Interleaved baseline vs final, 3 repetitions per point, one worker, one machine:

| | Baseline | Final | Note |
|---|---|---|---|
| Hit path p50 @ 300 rps | 1.87 ms | 1.16 ms (−38 %) | CI95 ±0.1 ms |
| Hit path p99 @ 600 rps | 64.7 ms | 6.8 ms | |
| API CPU @ 500 rps | 74 % | 36 % | per-request CPU ≈ halved |
| Clean throughput before collapse | ≈ 600–650 rps | ≈ 700–800 rps | > 850 generator-limited; collapse = goodput falls to ≈ 280/s |
| Burst 5× × 5 s | p50 710 ms, 1.5 % errors | 2.2 ms, 0 | |
| Redis node outage (stop / freeze) | 36–38 % errors, 17 s unavailable | 0 % errors | |
| 200 simultaneous identical misses | 3.5–10 DB queries/prefix | exactly 1 | |
| Flush of 100 queries | ≈ 500 ms | ≈ 14 ms | |
| Lost updates, 6 flushers | 67–70 % | 0 % | |
| Miss-path latency (cold/mixed/high-cardinality/read-write at ≤ 150 rps) | — | within noise (≤ −20 % at best) | the cache is not the dominant cost; PostgreSQL + network are |
| PostgreSQL frozen | 30 % errors | 26 % errors | **not solved** |

Honest caveats: the first (non-interleaved) matrix measured the same baseline code ≈ 2× slower and with a ≈ 300 rps knee — machine drift,
which is why only interleaved comparisons are used. The final code in the 240-point matrix was `v_final`; two later changes (retry disable; skipping the unconditional
cache re-check) were validated in isolation (outage ×4 runs, high-cardinality ×4, stampede ×5), not by re-running the whole matrix.

## 6. Claims review (documentation/benchmarks vs evidence)
| Claim | Verdict | Evidence |
|---|---|---|
| "100,000 concurrent requests" (`docs/performance-report.md`) | **False as worded** | `final_benchmark.py` sends chunks of 100 and waits for each chunk (closed loop) |
| "97.29 % cache hit rate, DB shielded" | **Artefact** | 10 000 synthetic `query_item_N` keys that are not in the dataset (cached as empty results); for that stream a cold cache cannot exceed 95.6 %; this says nothing about real prefixes (the dataset-derived mixed workload from a cold cache: 35–44 % hit rate) |
| "197 RPS sustained … Warm 420 ms p50 is queueing" | Not reproducible here | measured warm p50 1.1–2 ms at 100–600 rps (open loop, baseline up to ≈ 600 rps clean); their run's configuration/hardware is unknown and it used 100-request closed-loop chunks, so the two are not comparable |
| "Redis-a took 60 % because of consistent hashing hot key" | **Correct but workload-driven** | reproduced: 59.7–60.3 % over 20 seeds; rank-1 key = 25 % of requests (`exp_claims.py`) |
| "500 vnodes ⇒ 33.86/34.58/31.57 %, < 2 % deviation" | **Accurate** | reproduced exactly; max deviation 1.76 pts |
| "Adding a 4th node moves 26.44 % vs 74.9 % for modulo" | **Accurate** | 26.36 % (ideal 25 %) |
| "Dead node's vnodes are instantly deleted; 100 % available" | **False** | no such code; measured 36–38 % errors |
| "Active prefix invalidation" | **False (baseline)** | F-03 |
| "Sub-millisecond autocomplete" (README) | **Not supported** | server-side `X-Response-Time-ms` on cache hits (sequential, 1 500 requests): baseline p50 1.61 / p99 2.44 ms; final p50 0.87 / p95 1.26 / p99 1.80 ms. End-to-end HTTP p50 1.1–2 ms (hit) and 4–6 ms (miss) in the load runs |
| "Trending ranking (history + 10·recent)" | **Not implemented** | F-10 |
| Write reduction 74.31 % / 95.37 % | Simulation, not the system | `write_sensitivity.py` is unseeded, ignores the 10 s trigger and counts rows, not statements |
| `BUFFER_SIZE` env var | Wrong name | actual `WRITE_BUFFER_SIZE`; unit is *distinct queries* |
| "Phase 1 PostgreSQL p50 7.48 ms" in the generated report | Hard-coded constants | `final_benchmark.py` |

## 7. Remaining risks and limitations
1. Hung database (F-27) — requests pile up for the whole outage; needs per-request deadlines.
2. Durability — in-memory buffer; crash loses ≤ ~10 s of counter updates; no replay. Acceptable only if popularity counters are non-critical.
3. No authentication/rate limiting on `/search`; poisoning and shedding remain possible.
4. Trending ranking decision (F-10); dead index costs write maintenance (unmeasured at 3.2 MB / 150 k rows).
5. Everything is single-host/Windows/Docker-Desktop evidence; multi-worker scaling, Linux, large datasets, Redis eviction, soak and slow-dependency faults are unmeasured.
6. Frontend has no automated tests; cancellation/out-of-order behaviour verified by inspection only; 2 pre-existing lint errors remain (`set-state-in-effect`).
7. The new `ENABLE_DEBUG_ENDPOINTS` default is on (compatibility); `CACHE_PROVIDER` unknown ⇒ silent in-memory fallback (F-29).
8. Per-process coalescing and metrics under `--workers N`; the cache-aside invalidation race (≤ TTL) is accepted.

## 8. Recommended next steps (ordered by value / cost)
1. Decide ranking semantics (F-10), then drop or fix `idx_trending_score`.
2. Add a gateway/auth + rate limit for `/search`, set `ENABLE_DEBUG_ENDPOINTS=false`, `requirepass`/ACLs, `maxmemory` + `allkeys-lru` on Redis.
3. Introduce request deadlines for database calls (async driver or `statement_timeout` + connection invalidation) and test with `docker pause` (F-27).
4. Add CI running `pytest` (unit always, integration against service containers), `bandit`, `pip-audit`, `tsc`, `next build`; add an application Dockerfile (non-root).
5. Re-run the matrix on Linux with `--workers 2/4` and the generator on another host; add a ≥ 1 M-row dataset and a 24 h soak.
6. Only if durability of counters matters: append-only local journal or Redis stream *before* buffering (justified by the measured ≤ 10 s exposure, not before).

## 9. Final verification checklist
| Item | Result |
|---|---|
| Tests | **121 passed** (62 need no services; 59 integration tests run against real PostgreSQL 15 + Redis 7 and are skipped with a reason when the two environment variables are absent); 89 % line coverage of `app/`; also 121/121 in a clean venv with the newest resolvable dependencies (Starlette 1.8, FastAPI 0.143, SQLAlchemy 2.1, pytest 9) |
| Mutation check | 13 re-introduced defects (`benchmarks/mutation_smoke.py`): **13/13 killed**; three survivors were first found and fixed in the *mutants/tests* (equivalent mutant, probabilistic deadlock test, wrong retry mutant) |
| Static analysis | bandit: no issues after `usedforsecurity=False` on MD5 and a `nosec` on jitter; ruff F,B,S: clean; pip-audit: new lock 0 CVEs (old lock 12); `tsc --noEmit`: clean; eslint: 2 pre-existing errors remain (3 fixed) |
| Frontend build | `next build` OK on Windows; `npm ci` + `tsc` OK on Linux (node:22-alpine); Linux `next build` not run (needs network for Google Fonts) |
| Benchmarks | 14 scenarios × baseline/final interleaved (240 points × 20–120 s); extra: saturation sweep, 4 outage re-runs, high-cardinality ×4, stampede ×15, write-freeze ×2, lost-update ×3, node-down-at-start ×2, flush-duration ×9 |
| Optimizations applied | O-1 … O-6 (+ reliability changes); each with isolated A/B in `OPTIMIZATIONS.md` |
| Regressions detected and resolved | extra Redis GET per miss from my single-flight re-check (+0.93 commands/request) → gated; first breaker version still stalled 5 s due to redis-py retries → retries disabled; an early "99 % loss" reading of the write-freeze test was a measurement bug → corrected |
| Blocked / not done | multi-worker, Linux, large dataset, soak, slow-dependency injection, browser E2E, container hardening (no Dockerfile), CI, authentication |
| Known unresolved | F-10, F-27, F-11 (auth), F-13 default, F-29, F-31 |
