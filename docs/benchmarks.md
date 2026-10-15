# Benchmarks

What was measured, how, and what the results do and do not support. Raw data and full tables: [`audit/BENCHMARK_RESULTS.md`](../audit/BENCHMARK_RESULTS.md); tooling: [`benchmarks/`](../benchmarks/README.md).

## Method (why the numbers can be trusted — and where they can't)
* **Open-loop load.** Requests are scheduled at a fixed arrival rate and latency is measured from the *intended* send time. A closed loop ("send, wait, send") slows itself down when the server is slow and hides queueing (coordinated omission); the project's original benchmark was closed-loop in chunks of 100 and its "100 000 concurrent requests" never exceeded 100 in flight.
* **Generator validity.** Dispatch lag is recorded for every request; Windows timers (8–15 ms granularity) are bypassed by spinning. Above ≈ 850 rps the generator itself lags, so results there show trends, not capacity.
* **Interleaved A/B.** The same code measured 2× differently across hours on this machine, so every headline comparison alternates *baseline, candidate, baseline, candidate …* per repetition. Absolute numbers are machine-specific; only same-session comparisons are claimed.
* **Workloads.** Real query strings and popularity from the 150 000-row corpus; synthetic typing cascades (stop positions, interleaving), uniform high-cardinality, popular-100, Zipf, 95/5 read-write, bursts, sustained; plus fault scenarios. No production traffic exists, so request-level realism is not claimed.
* **Evidence from outside the app.** Hit rates from Redis `INFO`, DB work from PostgreSQL statement logs / `pg_stat_*`, CPU/RSS from the OS.
* **Repetitions:** 3 per point (5 for the stampede); medians with min–max, 95 % block-bootstrap CIs on raw per-request data.
* **Environment:** one 16-thread Windows 11 laptop, Docker Desktop (PostgreSQL 15, 3× Redis 7), one uvicorn worker, loopback.

## Results (original code vs. current)
| Scenario | Original | Current |
|---|---|---|
| Warm hit path p50 @ 100 / 300 / 600 rps | 2.06 / 1.87 / 1.91 ms | **1.46 / 1.16 / 1.09 ms** |
| Warm hit path p99 @ 600 rps | 64.7 ms | **6.8 ms** |
| API CPU @ 500 rps (cache hits) | 74 % | **36 %** |
| Saturation (single worker, cache hits) | clean ≤ ≈ 600–650 rps; ≥ 700 rps collapses to ≈ 280 ok/s (60–98 % errors) | clean at 700, ≈ 800 ok/s at 850; > 850 generator-limited |
| 5× burst for 5 s (100 → 500 rps) | p50 710 ms, 1.5 % errors | **2.2 ms, 0 errors** |
| Redis node stopped / frozen mid-run | 36–38 % errors, 16–17 s with no successes | **0 % errors**, p99 ≈ 9 ms |
| PostgreSQL frozen 20 s | 14 s with no successes, requests hang ≈ 6 s | **0 s**; failures ≤ 2 s; cached prefixes unaffected |
| 200 simultaneous identical misses | 3.5–10 DB queries (p50 ≈ 430 ms) | **1** (p50 ≈ 180 ms) |
| Flush of 100 distinct queries | ≈ 500 ms | **≈ 14 ms** |
| 6 concurrent flushers, 720 events | 216–234 stored (67–70 % lost) | **720** |
| Cache-less (every request hits PostgreSQL) @ 400 rps | p50 4.1 ms, p99 18 ms | p50 2.7 ms, p99 8.3 ms (+≈ 0.4 ms median for the database guard, measured separately) |
| Miss-path latency (cold, mixed, high-cardinality, read-write, ≤ 150 rps) | — | **no consistent change** (paired differences within noise; dominated by PostgreSQL + network) |
| Sustained 120 rps × 120 s | p50 3.6 ms, flat | p50 2.3 ms, flat; RSS 93 MB, no leak |

## Where the improvement came from (isolated A/B, 3 interleaved reps each)
Settings object cached per process (−27 % CPU, p50 −22 %), cached JSON document served without re-validation (−12…16 % CPU), plain-ASGI timing middleware (−7…15 % CPU, no latency change), single-flight for concurrent misses, one-statement upsert and batched `DEL`s for the write path. The correctness and reliability fixes alone changed nothing on the hot path. Details: [`audit/OPTIMIZATIONS.md`](../audit/OPTIMIZATIONS.md).

## Things that surprised me
* The database path is nearly as fast as the cache at this scale (≈ 4–6 ms vs 1–2 ms end-to-end): the cache's value here is **CPU relief and load shedding**, not raw latency. This is dataset-size dependent and is stated as such.
* The first benchmark pass measured the *same* baseline code at ≈ 2× the latency and a "knee" at 300 rps; later interleaved runs put the knee near 650. Un-interleaved comparisons on a shared machine can mislead.
* A single 500-key `DEL` stalled ≈ 95 ms through Docker Desktop's port proxy while 100-key commands take ≈ 2 ms per 600 keys — platform-specific, found by measurement, handled with a chunk size.

## Limits of the evidence
Single machine, single worker, synthetic typing behaviour, loopback networking. Not measured: multi-worker scaling, Linux, million-row corpora, Redis eviction behaviour, soak > 2 minutes, slow-but-alive dependencies. See [`audit/CAPACITY_AND_LIMITS.md`](../audit/CAPACITY_AND_LIMITS.md).

## Reproducing
```bash
docker compose -p taxaudit -f benchmarks/docker-compose.bench.yml up -d      # disposable stack on ports 47xxx
source benchmarks/env.sh
python backend/ingest.py --dsn "$PG_DSN"
bash benchmarks/run_matrix_ab.sh <baseline-checkout> .                        # ≈ 3 h; see audit/REPRODUCING.md
```
The pre-audit code is commit `a45f129` (`git archive a45f129 | tar -x -C /tmp/baseline`).
