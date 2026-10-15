# Benchmarks

What was measured, how, and what the results do and do not support. Raw data and full tables: [`docs/benchmark-details.md`](./benchmark-details.md); tooling: [`benchmarks/`](../benchmarks/README.md).

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
Settings object cached per process (−27 % CPU, p50 −22 %), cached JSON document served without re-validation (−12…16 % CPU), plain-ASGI timing middleware (−7…15 % CPU, no latency change), single-flight for concurrent misses, one-statement upsert and batched `DEL`s for the write path. The correctness and reliability fixes alone changed nothing on the hot path. Details: [`docs/optimizations.md`](./optimizations.md).

## Things that surprised me
* The database path is nearly as fast as the cache at this scale (≈ 4–6 ms vs 1–2 ms end-to-end): the cache's value here is **CPU relief and load shedding**, not raw latency. This is dataset-size dependent and is stated as such.
* The first benchmark pass measured the *same* baseline code at ≈ 2× the latency and a "knee" at 300 rps; later interleaved runs put the knee near 650. Un-interleaved comparisons on a shared machine can mislead.
* A single 500-key `DEL` stalled ≈ 95 ms through Docker Desktop's port proxy while 100-key commands take ≈ 2 ms per 600 keys — platform-specific, found by measurement, handled with a chunk size.

## Linux, free, and multi-worker: GitHub Actions
Everything above ran on one Windows laptop. To close the "is this just Windows?" gap for free, [`benchmark.yml`](../.github/workflows/benchmark.yml) runs the same interleaved original-vs-current comparison on a GitHub-hosted Linux runner (Ubuntu, 4 vCPU, 15.6 GB, PostgreSQL 15 and 3× Redis 7 as service containers, Python 3.11, uvicorn with uvloop/httptools, kernel 6.17 Azure). Trigger it from the Actions tab (or push a `bench/**` branch); results land as a downloadable artifact. Data: `benchmarks/results/lx1_*` (1 worker), `lx2_*` (2 workers), tables in `summary_linux_w1.md` / `summary_linux_w2.md`.

| Hit path, cache warm | Original | Current |
|---|---|---|
| 200 rps · 1 worker | p50 2.51 ms, CPU 46 % | **p50 1.26 ms, CPU 19 %** |
| 500 rps · 1 worker | 61 OK/s, 99.5 % errors (collapse) | **500 OK/s**, p50 1.09 ms, p99 3.9 ms, CPU 44 % |
| 900 rps · 1 worker | 0 OK (100 % errors) | **900 OK/s**, p99 6.7 ms, CPU 78 % |
| 1 300 rps · 1 worker | 0 OK | 217 OK/s (93 % errors) — saturated |
| 900 / 1 500 rps · 2 workers | 0 OK (100 % errors) | **900 / 1 500 OK/s**, 0 errors |
| 2 200 rps · 2 workers | 15 OK/s | 1 188 OK/s (58 % errors) — saturated |
| Mixed (cache cold start) 200 rps | p50 3.69 ms, CPU 54 % | p50 2.73 ms, CPU 29 % |
| Cache-less (every request hits PostgreSQL) 200 rps | p50 3.54 ms | p50 2.52 ms |
| 200 simultaneous identical misses × 20 keys | 341–408 transactions (≈ 17–20 per key), p50 383 ms | 41–47 transactions (≈ 2 per key), p50 121 ms |

How to read it:
* **Direction and size agree with the laptop** — per-request CPU is cut by roughly half or more (−46 … −60 %), and the original code saturates much earlier. On this runner the original code was already collapsed at the first overloaded rate we tried (500 rps) while the current code held 900 on one worker; on the laptop the gap at the knee was smaller (≈ 600–650 vs 700–800). The knees were **not bracketed** (no rates between 200 and 500 for the original, none between 900 and 1 300 for the current), so no precise ratio is claimed.
* **Multi-worker:** 2 workers served 1 500 rps with no errors (hit path, generator on the same 4 vCPUs) — evidence that the design scales with processes at least to 2, within the limits of a shared runner. Writes stay correct across workers because the merge is atomic in SQL; coalescing and breakers are per process.
* **The database path saturates below 500 rps on this runner** for both versions (cache-less and cold-start `mixed` at 500 rps: 0–152 OK/s) because PostgreSQL, Redis, the API and the load generator share 4 vCPUs — a statement about the runner, not about the code.
* **Noise:** shared runner, one run, 3 repetitions. Single points are unreliable (e.g. the 2-worker 900 rps p50 of 42 ms vs 2.5 ms at 1 500 rps is neighbour noise); interleaving keeps the comparison fair. The stampede's *statement* count needs the PostgreSQL log (not available to service containers), so transactions are reported instead.
* Fault-injection scenarios (kill Redis, freeze PostgreSQL) need `docker stop/pause` and were not run in CI; they are covered by the laptop results above and by unit/integration tests in CI.

## Limits of the evidence
One laptop plus one shared CI runner, at most 2 workers, synthetic typing behaviour, loopback networking. Not measured: scaling beyond 2 workers, a separate load-generator host, million-row corpora, Redis eviction behaviour, soak > 2 minutes, slow-but-alive dependencies. See [`docs/capacity-and-limits.md`](./capacity-and-limits.md).

## Reproducing
```bash
docker compose -p taxbench -f benchmarks/docker-compose.bench.yml up -d      # disposable stack on ports 47xxx
source benchmarks/env.sh
python backend/ingest.py --dsn "$PG_DSN"
bash benchmarks/run_matrix_ab.sh <baseline-checkout> .                        # ≈ 3 h; see benchmarks/REPRODUCING.md
```
The original code is commit `a45f129` (`git archive a45f129 | tar -x -C /tmp/baseline`).
