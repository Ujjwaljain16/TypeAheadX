# Benchmark results

Everything here was produced by the scripts in `benchmarks/` on the machine described below; raw per-request
data (`t_rel_s,latency_ms,status,send_lag_ms`) is in `audit/results/<label>/raw/*.csv.gz`, per-run summaries in
`audit/results/<label>/<scenario>.json`, full tables with confidence intervals in `audit/results/summary_ab.md`
(+ `.csv`), the compact comparison in `audit/results/summary_compare.md`.
**Read §0 and §9 before quoting any number.**

## 0. What these numbers are — and are not

* **Single desktop machine, no isolation.** Generator, API (1 uvicorn worker), PostgreSQL and 3 Redis containers
  share one 16-thread Windows 11 laptop/desktop (16 GB RAM) running Docker Desktop; traffic goes over loopback
  through Docker's port proxy. Absolute latencies are therefore *machine-specific and noisy*.
* **Drift is real.** The identical baseline code measured warm-cache p50 ≈ 3.4–4.1 ms (first, non-interleaved matrix,
  `audit/results/baseline/`) and ≈ 1.8–2.1 ms two hours later (`ab_baseline`). The first matrix's absolute numbers
  (and its apparent saturation at ≈ 300 rps) are **not** comparable with later runs and are kept only as a sanity set.
  All headline comparisons are **interleaved** (baseline run, then final run, per repetition).
* **Workload realism.** Query strings/popularity are real (150 000-row dataset); request streams are synthetic
  typing cascades. This is *not* production traffic and says nothing about the true hit rate of a production system.
* **Code versions.** `baseline` = commit `a45f129` (pre-audit). The headline matrix ran variant **v_final**. Two small,
  separately measured changes came after it and are *not* in the matrix: (a) Redis retries disabled (fixes the outage
  transition, §6) and (b) the cache re-check only after a just-finished flight (removes one Redis GET per miss, §5).
  The shipped code is `v_final3` (= working tree). Hit-path (`warm`) results are unaffected by (a) and (b)
  (neither executes on a hit); miss-path results of the matrix are slightly pessimistic for the final code.
* **Python libraries** for *all* benchmark runs: the old pinned set in `.venv` (FastAPI 0.136.3, Starlette 1.2.1,
  SQLAlchemy 2.0.50, psycopg 3.3.4, redis-py 8.0.0, uvicorn 0.49.0), so that variants differ only in application code.
* Latency = client-observed, from the **intended** send time (open loop). Percentiles are over successful (HTTP 2xx)
  requests; error/timeout rate is reported separately (client timeout 5 s counts as failure).

## 1. Environment (from `audit/results/ab_final/environment.json`)
Windows 11 (10.0.26200), 16 logical CPUs, 16 GB RAM · Python 3.11.9 · PostgreSQL 15.19 (alpine, default config:
`shared_buffers=128MB`, `max_connections` default; container limit 2 CPU / 2 GB, data on tmpfs) · Redis 7 ×3 (1 CPU / 512 MB each,
`maxmemory` unset, policy `noeviction`) · uvicorn single worker, SQLAlchemy pool 5 + 10 overflow (baseline defaults) ·
dataset: 150 000 rows, counts 2…987 (Σ = 876 322), avg length 19.1 chars, ASCII lowercase, no `%`/`_`/`\`.
Index sizes (15 MB table): `queries_pkey` 3.4 MB, `queries_query_key` 7.9 MB, `idx_query_prefix` 7.9 MB, `idx_trending_score` 3.2 MB (0 scans).

## 2. Query plans (PostgreSQL, `EXPLAIN (ANALYZE, BUFFERS)`, `benchmarks/sql_plans_baseline.sql`)
| Prefix | Plan | Rows scanned | Execution |
|---|---|---:|---:|
| `a` (6 177 matches) | Bitmap Index Scan `idx_query_prefix` → Bitmap Heap → top-N sort | 6 177 | 3.6 ms (1 809 buffers) |
| `iphone 15` (219 matches) | same | 219 | 0.36 ms |
| `zzzzzz` (none) | Index Scan | 0 | 0.04 ms |
| forced *generic* plan for `iphone 15` | Seq Scan, 151 788 rows filtered | 151 807 | 11.1 ms (30× worse) |

The generic-plan risk (prepared statements after 5 executions) was tested through the real SQLAlchemy/psycopg path: 60
repeated executions stayed at ≈ 2 ms → **not reproduced**. Top-N sort over all matches makes 1–2 character prefixes the
most expensive queries; they are also the most cacheable. After the `ESCAPE` change the index is still used (60 000-row
test: `idx_query_prefix` in the plan, no Seq Scan).

## 3. Headline: baseline vs final, interleaved, 3 repetitions (20 s measured + 5 s warm-up)
Medians over repetitions; full min–max and bootstrap CIs in `summary_ab.md`. "ok rps" is achieved successful throughput.
"API CPU" = process CPU % of one core. *Redis-side hit % is not comparable between variants* (see note).

### 3.1 Warm cache (hit path), offered-rate sweep
| rps | p50 base → final (ms) | p99 base → final (ms) | CPU % base → final | err base/final |
|---:|---|---|---|---|
| 100 | 2.06 → 1.46 (−29 %) | 3.9 → 3.8 | 13 → 9 | 0 / 0 |
| 200 | 1.92 → 1.26 (−34 %) | 3.2 → 2.4 | 33 → 19 | 0 / 0 |
| 300 | 1.87 → 1.16 (−38 %) | 3.6 → 2.0 | 45 → 23 | 0 / 0 |
| 400 | 1.82 → 1.09 (−40 %) | 4.8 → 1.9 | 64 → *6†* | 0 / 0 |
| 500 | 1.78 → 1.10 (−38 %) | 11.5 → 2.2 | 74 → 36 | 0 / 0 |
| 600 | 1.91 → 1.09 (−43 %) | 64.7 → 6.8 | 87 → 40 | 0 / 0 |

Sample counts 6 000–36 000 per point; bootstrap 95 % CI of p50 is ±0.1 ms or tighter at every rate (e.g. 300 rps: 1.9–1.9 vs 1.2–1.2 ms).
† the final 400-rps CPU figure is a sampler glitch in one repetition (`psutil` handle churn); the neighbouring points (23 %, 36 %) are representative.

### 3.2 Saturation (warm, single worker; `sat_*` labels, 2 interleaved reps; `summary_saturation.md`)
| offered rps | baseline: ok rps / err / p50 | final: ok rps / err / p50 |
|---:|---|---|
| 600 (matrix) | 600 / 0 / 1.9 ms (p99 65 ms, CPU 87 %) | 600 / 0 / 1.1 ms (p99 6.8 ms, CPU 40 %) |
| 700 | **280 / 60 % / 3.6 s** | 700 / 0 / 2.6 ms (p99 229 ms, CPU 85 %) |
| 850 | 274 / 69 % / 3.5 s | 818 / 5 % / 2.2 s |
| 1 000 | 274 / 73 % / 3.6 s | 786 / 22 % / 2.6 s |
| 1 200 | 275 / 78 % / 5.2 s | 731 / 41 % / 3.1 s |
| 1 500 | 101 / 98 % / 4.6 s | 487 / 77 % / 4.7 s |

The baseline's first bottleneck is the single API process's CPU (≈ 100 % of a core): above ≈ 650 rps it enters congestion
collapse (queue grows, requests exceed the 5 s client timeout, goodput *falls* to ≈ 280/s). The final code holds ≈ 700 rps clean and ≈ 800 rps goodput
before collapsing. **Above ≈ 850 rps the load generator's own dispatch lag (p99 75–2 000 ms) contaminates the measurement, so
capacity beyond that is unmeasured**; the improvement in sustainable throughput is therefore ≈ +15…25 % (≈ 650 → ≈ 750–800 rps), much
smaller than the −45 % CPU per request, because at the knee the single event-loop thread, not total CPU, is the limit. Multi-worker
scaling was not measured.

### 3.3 Other workloads (medians; hit-path variants fastest, miss paths dominated by PostgreSQL + network)
| scenario | rps | p50 base → final | p99 base → final | notes |
|---|---:|---|---|---|
| popular (top-100 prefixes, prewarmed) | 100 | 4.77 → 2.33 | 11.4 → 4.8 | baseline p50 higher than `warm` for an unexplained reason (not investigated) |
| popular | 300 | 6.18 → 1.57 | 1 253 → 5.5 | baseline starts shedding (0.5 % err) |
| popular | 400 | **3 358 → 1.28** | 5 563 → 2.7 | baseline 31.5 % errors, ok 290/s; final 400/s, 0 errors |
| mixed cascades (cold start) | 100 | 4.37 → 4.08 | 7.4 → 6.7 | miss path ≈ equal; CPU 24 → 14 % |
| mixed | 300 | 3.99 → 2.98 | 11.4 → 6.4 | baseline 0.4 % errors (3 reps) |
| zipf(1.1) synthetic | 200 | 2.26 → 1.40 | 7.2 → 5.6 | CPU 38 → 18 % |
| read 95 % / write 5 % | 200 | 4.26 → 5.42 *(reps: 4.26, 4.22, 8.16 vs 5.42, 5.45, 3.33)* | 33 → 9.8 | no consistent p50 difference; large run-to-run noise |
| read/write | 300 | **3 220 → 3.57** | 4 949 → 10.1 | baseline collapses (30 % errors, 216 ok/s) |
| cold unique prefixes | 100 | 4.51 → 3.92 | 7.9 → 6.9 | miss path |
| high-cardinality (4 interleaved reps, `ab3`) | 100 | 6.2–6.7 → **4.7–5.1** | 9–13 → 8–10 | final3; 1.93 Redis commands/request (same as baseline) |
| PostgreSQL only (no cache) | 400 | 4.09 → 2.66 | 18.0 → 8.3 | DB path not saturated at 400 rps; capacity of the DB path unmeasured |
| sustained 120 rps × 120 s | 120 | 3.58 → 2.28 | 6.1 → 4.1 | p50 flat across four 30-s windows (3.54/3.64/3.76/3.62 vs 2.23/2.29/2.29/2.32), RSS 93 MB both (no leak) |
| burst (5× for 5 s, base 100 rps) | 100/500 | **710 → 2.15** | 3 122 → 4.4 | baseline 1.5 % errors; final 0 |

Note on "hit %": the Redis keyspace counters count every GET. The final code's leader re-check (v_final) issues an extra GET per miss, so
`mixed` shows 21 % instead of 35 % although the share of requests served from cache is the same. DB work per request is the
variant-independent measure: PostgreSQL transactions per 1 000 requests (mixed 200 rps): baseline 573–597, final 585–599.

### 3.4 Where the CPU saving comes from
Measured in isolation (`OPTIMIZATIONS.md`): settings cache −27 % CPU, raw-JSON hit path −12…16 %, plain-ASGI middleware −7…15 %.
Correctness/reliability fixes alone: no change (warm 250 rps: p50 1.92 vs 1.89 ms, CPU 38.4 vs 37.4 %).

## 4. Stampede: 200 simultaneous identical misses × 20 prefixes (5 interleaved reps, exact statements counted from the PostgreSQL log)
| variant / session | DB queries per prefix (ideal 1.0) | burst p50 (ms) | burst p99 (ms) |
|---|---|---|---|
| baseline, headline matrix (`ab_baseline`) | 3.5, 4.8, 4.2, 4.8, 5.2 | 427–449 | 552–658 |
| final (v_final), matrix (`ab_final`) | **1.0 ×5** | 174–196 | 319–393 |
| baseline, `ab3` session | 4.6, 4.8, 6.7, 6.2, 5.8 | 428–441 | 536–802 |
| final3, `ab3` session | **1.0 ×5** | 174–193 | 280–340 |
| baseline, earlier session (`p4`, log-based count) | 6.5–10.1 | 237–272 | 340–445 |

The baseline's duplicate-query count depends on timing/load (3.5–10.1 across sessions); the single-flight result is exactly 1.0 in every run.
Burst latency is ≈ 2.3× lower at the median with the final code (includes the CPU optimisations O-1…O-3, not only coalescing).

## 5. Write path
| Measure | baseline | final | evidence |
|---|---|---|---|
| Flush of 100 distinct queries (DB write + cache invalidation) | 493–561 ms | **13–15 ms** | `exp_flush_duration` ×3 interleaved, 30 rounds each |
| ↳ DB write alone (100 rows) | SELECT + 100× upsert | 5.7 ms (one statement) | micro-timing |
| ↳ invalidation (1 621 keys) | ≈ 250 ms (and **targeted the wrong keys**) | ≈ 2–7 ms | `delete_many`, chunk 100 (500-key chunks: 96 ms) |
| Lost updates, 6 flushing processes (720 events) | **234 and 216 stored (67.5 % / 70.0 % lost)** | 720 (0 % lost) | `exp_lost_update` |
| One 6 000-char query in a batch with 4 good ones | all 5 events lost | good rows persisted, bad row dropped and counted | probe + tests |
| PostgreSQL frozen for ≈ 2.5 min while 150 000 unique `POST /search` arrive | all 150 000 accepted; buffer grew unbounded (RSS 82 → 112 MB); all persisted after recovery (≈ 16 s) | 50 537 accepted, 99 463 rejected with **503** and counted (`events_dropped`); RSS 83 → 99 MB; all accepted persisted | `exp_write_freeze` |

The write-freeze row corrects an early reading (a drain check that looked only at buffer size suggested 99 % loss in the baseline; that was an
experiment artefact and is *not* a finding). The trade-off of the cap: under extreme unique-query floods the final code sheds new distinct queries
(HTTP 503) instead of buffering without bound; `WRITE_BUFFER_MAX_UNIQUE` (default 50 000) is configurable.

## 6. Redis node failure (outage scenario: 100 rps warm cache, redis-b faulted at t = 15 s, restored at t = 35 s of a 55 s run; 2 repetitions each)
| fault type | variant | success | error rate | p99 (ms) | seconds with **zero** successes | degraded seconds |
|---|---|---:|---:|---:|---:|---:|
| `docker stop` | baseline | 3 205 / 5 000 and 3 134 / 5 000 | 36–37 % | 5 057–5 527 | 16–17 | 26 |
| `docker stop` | final3 (retries off) | 5 000 / 5 000 ×2 | **0** | 8.6–9.0 | **0** | 0 |
| `docker pause` (black hole) | baseline | 3 094, 3 161 / 5 000 | 37–38 % | 4 799–5 625 | 17 | 26 |
| `docker pause` | final3 | 5 000 / 5 000 ×2 | **0** | 8.7 and 184 | **0** | 1–3 |
| `docker stop` (matrix, v_final, redis-py default retries) | final | 4 960, 4 943 / 5 000 | 0.8–1.1 % | 4 361–4 851 | 0 | 7–8 |

* The baseline is *completely unavailable* for ≈ 17 s and recovers only after the node returns plus ≈ 7 s of backlog drain.
* v_final (breaker, but redis-py's default retry policy still active) already removed the sustained outage, but one failed call still cost
  4.8–7.6 s (measured directly: 250 ms timeout → 7 650 ms black hole / 4 825 ms refused port; with `Retry(NoBackoff(), 0)`: 266 / 253 ms). This is why the
  transition showed 5 s of high latency. `RedisNode` now disables client retries (regression test + mutant M13).
* Node recovery was **not** exercised end-to-end in these runs for the final code beyond the breaker unit tests and `exp_node_down_startup`
  (recovered node used again: 100 hits, 50 keys vs 0/0 in the baseline).
* Docker `stop`/`pause` on one host is a crude model of a partition; it demonstrates no real fault-domain independence.

## 7. PostgreSQL frozen (`docker pause`) at t = 30 s, released at t = 50 s (60 rps, mixed cascades from cold, 2 interleaved reps per variant; `g1_*` labels)
| variant | error rate | seconds with **zero** successes | seconds with > 1 s latencies | slowest request | p95 / p99 | OK during the 20 s freeze |
|---|---:|---:|---:|---:|---|---:|
| baseline | 27.1 % / 26.0 % | 14 / 14 | 22 / 22 | ≈ 6.0 s | 2.9–3.6 s / 4.6–5.3 s | 19 % / 22 % |
| previous fixed version (`final3`) | 22.7 % / 24.9 % | 12 / 13 | 20 / 21 | ≈ 6.0 s | 3.2–3.4 s / 4.8–5.1 s | 32 % / 25 % |
| **with the database guard** (deadline 2 s, bulkhead, breaker) | 25.8 % / 25.6 % | **0 / 0** | **2 / 2** | **2.0 s** (the deadline) | **6.8–9.5 ms / 17.6–18.0 ms** | 27 % / 27 % |

The error *rate* is the same by construction — cache misses cannot be answered while the database is frozen — but without the guard those misses held request threads for ≈ 5 s each and starved
everything else (zero successes for 12–14 s, including requests that were in the cache); with the guard they fail instantly with 503 and cached prefixes keep being served at normal latency. Recovery
after the database was released was observed in the timeline (successes resume within the breaker window, ≈ 5–6 s). Reads only: writes keep their blocking, at-most-once behaviour (FINDINGS F-27).

## 8. Resource use
* Redis: ≈ 540–700 bytes per cached prefix (3 nodes, 4.5–5 k keys ≈ 5.3–6.1 MB total incl. ≈ 1 MB empty overhead each). With `noeviction`
  and no `maxmemory`, cardinality is bounded only by TTL (300 s) × distinct-prefix arrival rate; a full-dataset extrapolation is *not* measured.
* API process RSS ≈ 82–93 MB steady in all scenarios; no growth over a 120 s sustained run.
* PostgreSQL: not saturated in any scenario (the cache-less path used ≈ 53 % of one API core at 400 rps; DB CPU was not recorded — `docker stats` sampling was
  implemented but not enabled in the runs because it perturbs timing).

## 9. Limitations and uncertainty (do not skip)
1. Three repetitions per point; run-to-run spread is substantial on miss-heavy workloads (e.g. highcard p50 4.5 / 6.1 / 9.5 ms in one variant).
   Paired differences were examined where medians looked contradictory; for `highcard`, `rw` and `mixed ≤ 150 rps` **no consistent p50 difference** exists.
2. Block-bootstrap CIs (1-s blocks) capture within-run sampling error, not between-session drift.
3. One worker, one host, loopback, Docker Desktop on Windows: no claim about Linux, multiple workers, multiple hosts or network RTT. Only 1 sustained run (120 s) — no soak test.
4. Generator limits: valid to ≈ 800 rps; beyond that dispatch lag invalidates latency (throughput/error trends still indicative).
5. Final-code outage numbers come from `final3`/`final2` re-runs, not from the 240-point matrix (the matrix used `v_final`).
6. Redis-side hit %, DB `pg_stat_*` and `docker stats` counters have ≈ 1 s publication delay or are variant-dependent as described above.
7. The first (non-interleaved) matrix in `audit/results/baseline/` shows 3–4 ms hit-path latency and a ≈ 300 rps knee for the *same* baseline code;
   that is machine drift/interference, which is exactly why it was not used for conclusions.

## 10. Commands
See `REPRODUCING.md` §6–7. Headline: `bash benchmarks/run_matrix_ab.sh <baseline_dir> <final_dir>` (≈ 3 h), then
`python benchmarks/report.py --labels ab_baseline ab_final --ci --out audit/results/summary_ab` and
`python benchmarks/compare.py ab_baseline ab_final audit/results/summary_compare.md`.
