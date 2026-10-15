# Reproducing the tests and benchmarks

All commands were executed on the machine described in `results/ab_final/environment.json`
(Windows 11, 16 logical CPUs, 16 GB RAM, Docker Desktop, Python 3.11.9, Node 22.19). Paths use the Windows
virtualenv layout (`.venv/Scripts/…`); on Linux/macOS replace with `.venv/bin/…`.

## 0. Prerequisites
Docker, Python 3.11+, Node 20+ (frontend only). Nothing else is required; no cloud services are used.

## 1. Disposable infrastructure
```bash
docker compose -p taxbench -f benchmarks/docker-compose.bench.yml up -d      # PG :47433, Redis :47379-47381
```
Ports 47xxx are deliberate: the repository's own `docker-compose.yml` uses 6379-6381/5433, and 6379 was
occupied on the benchmark machine. Data lives on `tmpfs` — `docker stop` of the PostgreSQL container loses it
(use `docker pause`/`unpause` for fault injection, as the scenarios do). Tear down: `docker compose -p taxbench down`.

## 2. Python environment (clean-install check)
```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements-dev.txt -r benchmarks/requirements.txt
# or the exact, vulnerability-checked set:  pip install -r backend/requirements-lock.txt
```
The original `requirements.txt` did **not** install a runnable app (`redis` missing) — finding F-01.

## 3. Load the dataset
```bash
source benchmarks/env.sh
.venv/Scripts/python backend/ingest.py --dsn "$PG_DSN"        # 150 000 rows, ~5 s
```

## 4. Tests
```bash
cd backend
source ../benchmarks/env.sh                      # sets TAX_TEST_PG_DSN / TAX_TEST_REDIS_NODES
../.venv/Scripts/python -m pytest tests -q       # 136 tests (71 need no services; 65 integration)
../.venv/Scripts/python -m pytest tests -q --cov=app --cov-report=term-missing
# without the two variables the 58 integration tests are skipped with an explicit reason
../.venv/Scripts/python ../benchmarks/mutation_smoke.py     # 12 re-introduced defects, all must be KILLED
```
Integration tests create/use database `typeaheadx_test` and **flush the Redis nodes listed** — they refuse to
run against a database whose name does not end in `_test` or a non-local host.

Static analysis: `python -m bandit -r backend/app`, `python -m ruff check backend/app --select F,B,S`,
`python -m pip_audit -r backend/requirements-lock.txt --no-deps`, frontend `npx tsc --noEmit && npm run lint`.

## 5. Baseline checkout
```bash
mkdir /tmp/baseline && git archive a45f129 | tar -x -C /tmp/baseline      # original code, byte-identical
```

## 6. Benchmarks
Single scenario (each rate × repetition restarts the API, resets Redis and DB stats):
```bash
.venv/Scripts/python benchmarks/run_bench.py --code /tmp/baseline --label baseline --scenario warm --rates 100,200,300 --reps 3
.venv/Scripts/python benchmarks/report.py --labels baseline --ci
```
Headline interleaved comparison (≈ 2.5 h; do nothing else on the machine meanwhile):
```bash
bash benchmarks/run_matrix_ab.sh /tmp/baseline "$PWD"
.venv/Scripts/python benchmarks/report.py --labels ab_baseline ab_final --ci --out benchmarks/results/summary_ab
```
Raw per-request data: `benchmarks/results/<label>/raw/*.csv.gz` (`t_rel_s,latency_ms,status,send_lag_ms`).

## 7. Experiments
```bash
.venv/Scripts/python benchmarks/exp_lost_update.py --code /tmp/baseline --label baseline     # then --code .
.venv/Scripts/python benchmarks/exp_node_down_startup.py --code /tmp/baseline --label baseline
.venv/Scripts/python benchmarks/exp_write_freeze.py --code /tmp/baseline --label baseline --events 150000
.venv/Scripts/python benchmarks/exp_flush_duration.py --code /tmp/baseline --label baseline
```
Results append to `benchmarks/results/experiments/*.jsonl`.

## 8. Profiling
```bash
.venv/Scripts/pip install py-spy
# start the API (see benchmarks/common.py:Server), then:
py-spy record --pid <python.exe child of uvicorn> --gil -d 20 -r 200 -f raw -o prof.raw
.venv/Scripts/python benchmarks/profile_summary.py prof.raw 40
```
(On Windows the venv's `python.exe` is a launcher stub; profile its child process.)

## 9. Known reproduction caveats
* Absolute latencies depend on machine load; only interleaved comparisons are claimed.
* Docker Desktop's port proxy adds latency and, for very large single Redis commands, a measured ~95 ms
  stall (see OPTIMIZATIONS.md O-5). Numbers on native Linux will differ.
* `docker pause` models a black-holed dependency; `docker stop` models a refused connection. Real
  network partitions may behave differently (kernel keepalive/RST timing).
* A 3-container Redis "cluster" on one host shares fate (power, kernel, disk, NIC). Nothing here demonstrates
  high availability or independent failure domains.
