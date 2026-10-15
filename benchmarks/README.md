# TypeAheadX benchmark suite

Open-loop load generator, deterministic dataset-derived workloads, scenario runner and fault-injection
experiments. Everything here runs against **disposable** infrastructure (`docker-compose.bench.yml`);
no scenario touches any database or Redis other than the ports listed in `env.sh`.

## Methodology (read before trusting a number)

* **Open loop.** `loadgen.py` schedules requests at a fixed arrival rate. Latency is measured from the
  *intended* send time, so an overloaded server (or generator) cannot hide queueing by slowing the offered
  load (coordinated omission). `send_lag` is recorded per request; a run whose generator lag p99 is
  more than a few ms is suspect. (On Windows the generator spins in the last 25 ms before each send because
  `asyncio.sleep` granularity can be 8–15 ms.)
* **Same machine.** Generator, API, PostgreSQL and Redis containers share one desktop-class machine, so
  absolute numbers include contention and Docker Desktop port-forwarding. Treat them as *relative* evidence.
* **Drift.** The same code measured p50 ≈ 3.5–4 ms in one hour and ≈ 1.8–2 ms two hours later. Therefore
  every headline comparison is **interleaved** (`run_ab.sh`: baseline, candidate, baseline, candidate …) and the
  first non-interleaved matrix is only reported as a sanity set.
* **Workloads.** Query strings and popularity weights are real (the 150 000-row AmazonQAC-derived CSV).
  Typing behaviour (cascades, stop positions, interleaving, 95/5 read/write) is synthetic — no production
  request log exists. Streams are seeded (`--seed`, default 1234) and identical across variants.
* **Repetitions.** 3 repetitions per point (5 for the stampede). Reports show the median and min–max over
  repetitions; `report.py --ci` adds a 95 % block-bootstrap CI (1-second blocks) from the raw per-request files.
* **Counters from outside the application.** Hit rates come from Redis `INFO stats`, DB work from PostgreSQL
  (`pg_stat_*`, statement log), CPU/RSS from `psutil` on the server process.

## Files

| File | Purpose |
|---|---|
| `docker-compose.bench.yml` | PostgreSQL 15 + 3×Redis 7 on ports 47433 / 47379-47381, resource-limited, tmpfs data |
| `env.sh` | environment for the API under test **and** the integration tests |
| `workload.py` | deterministic stream generators (cascade, uniform/high-cardinality, popular, Zipf) |
| `loadgen.py` | open-loop asyncio/aiohttp generator (fixed/Poisson/burst arrivals, timed fault events) |
| `common.py` | server lifecycle, infra counters, environment metadata |
| `run_bench.py` | one scenario × rates × repetitions → `audit/results/<label>/<scenario>.json` + raw gz |
| `run_matrix.sh` / `run_ab.sh` / `run_matrix_ab.sh` | full matrix; interleaved A/B; the headline baseline-vs-final run |
| `report.py` | tables (median, min–max, bootstrap CI) + CSV |
| `profile_summary.py` | aggregate a `py-spy record --gil -f raw` file |
| `exp_*.py` | fault/consistency experiments: lost updates, node down at start-up, write path during a DB freeze, flush duration |
| `mutation_smoke.py` | re-introduces the audited defects and checks the test-suite fails |

## Scenarios

| Scenario | What it measures |
|---|---|
| `cold` | unique prefixes, cache empty: the miss path (Redis GET miss → PostgreSQL → SET) |
| `warm` | all keys pre-loaded: the hit path; rate sweep finds the saturation knee |
| `mixed` | dataset-weighted typing cascades from an empty cache (natural hit/miss mixture) |
| `highcard` | uniformly random prefixes, almost no reuse |
| `popular` | only the 100 most popular prefixes |
| `zipf` | synthetic Zipf(1.1) over 50 000 prefixes |
| `rw` | 95 % reads / 5 % `POST /search` (write buffer, flush, invalidation) |
| `pgonly` | zero cache nodes: every request goes to PostgreSQL |
| `stampede` | 200 simultaneous identical misses × 20 keys; counts executed SQL from the PostgreSQL log |
| `outage` | one Redis node stopped (or `--outage-mode pause` = frozen black hole) mid-run; per-second timeline |
| `pgoutage` | PostgreSQL frozen (`docker pause`) mid-run, then released |
| `burst` | 5× arrival-rate bursts of 5 s |
| `sustained` | constant rate for minutes (drift/leak check) |

## Quick start

```bash
docker compose -p taxaudit -f benchmarks/docker-compose.bench.yml up -d
python -m venv .venv && .venv/Scripts/pip install -r benchmarks/requirements.txt   # (bin/ on Linux/macOS)
source benchmarks/env.sh
.venv/Scripts/python backend/ingest.py --dsn "$PG_DSN"            # 150 000 rows
.venv/Scripts/python benchmarks/run_bench.py --code . --label mine --scenario warm --rates 100,200 --reps 3
.venv/Scripts/python benchmarks/report.py --labels mine --ci
```

To compare against the pre-audit code: `git archive a45f129 | tar -x -C /some/dir` and pass that directory
as another `--code`. See `audit/REPRODUCING.md` for the complete procedure.
