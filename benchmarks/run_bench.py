"""Benchmark scenario runner.

Example:
  python benchmarks/run_bench.py --code <path-to-checkout> --label baseline \
         --scenario warm --rates 100,200,400 --reps 3 --duration 20 --warmup 5

Each (rate, repetition) point restarts the API server (fresh process, fresh pool,
fresh in-process metrics) and resets Redis (and DB statistics) so that points are
independent. Results are written to benchmarks/results/<label>/<scenario>.json plus a
gzip CSV of every measured request under benchmarks/results/<label>/raw/.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import aiohttp
import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import workload as W  # noqa: E402
from loadgen import run_open_loop  # noqa: E402

RESULTS = C.REPO / "benchmarks" / "results"

_DS = None


def dataset():
    global _DS
    if _DS is None:
        _DS = W.load_dataset()
    return _DS


def make_ops(scenario: str, n: int, seed: int) -> list[tuple]:
    qs, cnt = dataset()
    if scenario in ("warm", "mixed", "sustained", "burst", "outage", "pgoutage", "pgonly_cascade"):
        return [("GET", p) for p in W.cascade_stream(qs, cnt, n, seed)]
    if scenario in ("cold", "highcard"):
        return [("GET", p) for p in W.uniform_prefix_stream(qs, n, seed)]
    if scenario == "popular":
        return [("GET", p) for p in W.popular_stream(qs, cnt, n, seed)]
    if scenario == "zipf":
        return [("GET", p) for p in W.zipf_stream(qs, cnt, n, seed)]
    if scenario == "pgonly":
        return [("GET", p) for p in W.cascade_stream(qs, cnt, n, seed)]
    if scenario == "rw":
        rng = np.random.default_rng(seed + 1)
        gets = W.cascade_stream(qs, cnt, n, seed)
        writes = W_sample_queries(qs, cnt, n, rng)
        is_w = rng.random(n) < 0.05
        return [("POST", writes[i]) if is_w[i] else ("GET", gets[i]) for i in range(n)]
    raise ValueError(scenario)


def W_sample_queries(qs, cnt, n, rng):
    p = cnt / cnt.sum()
    return [qs[i] for i in rng.choice(len(qs), size=n, p=p)]


SERVER_ENV = {
    "pgonly": {"REDIS_NODES": ""},   # zero cache nodes -> every request goes to PostgreSQL
}
PREWARM = {"warm", "popular", "outage", "sustained", "burst"}


async def prewarm(ops, concurrency=32):
    keys = sorted({a for k, a in ops if k == "GET"})
    sem = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=concurrency)) as s:
        async def one(k):
            async with sem:
                async with s.get(C.BASE_URL + "/suggest", params={"q": k}) as r:
                    await r.read()
        await asyncio.gather(*[one(k) for k in keys])
    return len(keys)


def burst_offsets(base: float, mult: float, windows: list[tuple[float, float]], total_s: float):
    """Arrival times for ``base`` req/s with ``mult``x bursts inside ``windows`` (seconds)."""
    out, t = [], 0.0
    while t < total_s:
        out.append(t)
        r = base * (mult if any(a <= t < b for a, b in windows) else 1.0)
        t += 1.0 / r
    return np.asarray(out)


def app_cache_metrics():
    try:
        return C._HTTP.get(C.BASE_URL + "/cache/metrics", timeout=3).json()
    except Exception:
        return {}


def run_point(args, scenario: str, rate: float, rep: int, extra_env: dict, events_fn=None, tag="") -> dict:
    server = C.Server(Path(args.code), workers=args.workers, extra_env={**SERVER_ENV.get(scenario, {}), **extra_env},
                      log_path=C.REPO / "benchmarks" / "results" / args.label / f"server_{scenario}.log")
    (C.REPO / "benchmarks" / "results" / args.label).mkdir(parents=True, exist_ok=True)
    if scenario in ("rw",):
        C.reload_dataset()
    C.flush_redis()
    C.reset_pg_stats()
    server.start()
    total = int((args.warmup + args.duration) * rate)
    offsets = None
    if scenario == "burst":  # 5x bursts of 5 s at 1/3 and 2/3 of the measured window
        w, d = args.warmup, args.duration
        offsets = burst_offsets(rate, 5.0, [(w + d / 3, w + d / 3 + 5), (w + 2 * d / 3, w + 2 * d / 3 + 5)], w + d)
        total = len(offsets)
    ops = make_ops(scenario, total + 10, args.seed)
    info = {"stream_stats": W.stream_stats([a for k, a in ops if k == "GET"])}
    if scenario in PREWARM:
        t0 = time.time()
        info["prewarm_keys"] = asyncio.run(prewarm(ops))
        info["prewarm_seconds"] = round(time.time() - t0, 2)
        time.sleep(1.0)
    snaps = {}
    sampler = C.ResourceSampler(server)

    def at_measure_start():
        snaps["pg0"], snaps["redis0"], snaps["app0"] = C.pg_snapshot(), C.redis_snapshot(), app_cache_metrics()
        snaps["t0"] = time.time()
        sampler.start()

    events = events_fn() if events_fn else None
    res = asyncio.run(run_open_loop(C.BASE_URL, ops, rate, args.duration, warmup=args.warmup,
                                    timeout_s=args.timeout, on_measure_start=at_measure_start, events=events,
                                    offsets_override=offsets))
    res_usage = sampler.stop()
    time.sleep(1.5)  # pg_stat_database counters are flushed by backends with ~1s delay
    snaps["pg1"], snaps["redis1"], snaps["app1"] = C.pg_snapshot(), C.redis_snapshot(), app_cache_metrics()
    summ = res.summary()
    summ["wall_seconds"] = round(res.wall_seconds, 2)
    pgd, rd = C.diff_snap(snaps["pg0"], snaps["pg1"]), C.diff_snap(snaps["redis0"], snaps["redis1"])
    hits = sum(v.get("hits", 0) for v in rd.values())
    misses = sum(v.get("misses", 0) for v in rd.values())
    out = {
        "scenario": scenario, "tag": tag, "rep": rep, "rate": rate, "workers": args.workers, "seed": args.seed,
        "duration_s": args.duration, "warmup_s": args.warmup, "summary": summ, "resources": res_usage,
        "pg_delta": pgd, "pg_end": {k: snaps["pg1"][k] for k in ("active_conns", "total_conns")},
        "redis_delta": rd,
        "redis_hit_rate_pct": round(100 * hits / (hits + misses), 2) if hits + misses else None,
        "redis_end": snaps["redis1"],
        "app_cache_metrics_end": snaps["app1"], "server_env": extra_env, **info,
    }
    if args.timeline or scenario in ("burst", "sustained"):
        out["timeline"] = res.timeline(1.0)
    raw = RESULTS / args.label / "raw" / f"{scenario}{('_' + tag) if tag else ''}_r{int(rate)}_rep{rep}_w{args.workers}.csv.gz"
    C.write_raw(raw, "t_rel_s,latency_ms,status,send_lag_ms", res.records)
    out["raw_file"] = str(raw.relative_to(C.REPO)).replace("\\", "/")
    server.stop()
    if scenario == "rw":
        C.reload_dataset()  # leave the disposable DB pristine for the next scenario
    return out


def stampede(args, rep: int) -> dict:
    """Scenario I: N simultaneous identical cache misses for K distinct keys."""
    qs, cnt = dataset()
    rng = np.random.default_rng(args.seed + rep)
    keys = [qs[i][:6] for i in rng.choice(len(qs), size=40, replace=False)]
    keys = list(dict.fromkeys(keys))[:20]
    N = args.stampede_n
    server = C.Server(Path(args.code), workers=args.workers, extra_env={},
                      log_path=C.REPO / "benchmarks" / "results" / args.label / "server_stampede.log")
    C.flush_redis(); C.reset_pg_stats(); server.start()
    results = []

    async def all_bursts():
        res = []
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=N + 10)) as s:
            async def one(key):
                t = time.perf_counter()
                async with s.get(C.BASE_URL + "/suggest", params={"q": key}) as r:
                    await r.read()
                    return r.status, (time.perf_counter() - t) * 1000
            for key in keys:                      # one burst of N simultaneous identical requests per key
                res.extend(await asyncio.gather(*[one(key) for _ in range(N)]))
        return res

    def prefix_statements(since_ts: float) -> int:
        """Exact count of executed prefix SELECTs, from the PostgreSQL statement log."""
        o = subprocess.run(["docker", "logs", "--since", str(int(since_ts)), "taxbench-postgres"], capture_output=True, text=True)
        return (o.stdout + o.stderr).count("WHERE query LIKE")

    def prefix_scans():
        with C.pg_conn() as c:
            return int(c.execute("SELECT coalesce(sum(idx_scan),0) FROM pg_stat_user_indexes WHERE indexrelname='idx_query_prefix'").fetchone()[0])

    try:
        time.sleep(5)      # let start-up cache warm-up finish
        with C.pg_conn() as c:
            c.execute("ALTER SYSTEM SET log_statement = 'all'"); c.execute("SELECT pg_reload_conf()")
        time.sleep(1)
        t_start = time.time()
        pg0, sc0 = C.pg_snapshot(), 0
        allr = asyncio.run(all_bursts())
        time.sleep(1.5)
        pg1 = C.pg_snapshot()
        sc1 = prefix_statements(t_start)
        with C.pg_conn() as c:
            c.execute("ALTER SYSTEM RESET log_statement"); c.execute("SELECT pg_reload_conf()")
        lat = np.asarray([l for s, l in allr if s == 200])
        out = {"scenario": "stampede", "rep": rep, "workers": args.workers, "keys": len(keys), "concurrent_per_key": N,
               "total_requests": len(allr), "ok": int(len(lat)),
               "db_xacts_during_burst": pg1["xacts"] - pg0["xacts"],
               "db_prefix_queries": int(sc1 - sc0),
               "ideal_db_queries_single_flight": len(keys),
               "db_queries_per_key": round((sc1 - sc0) / len(keys), 1),
               "p50_ms": round(float(np.percentile(lat, 50)), 1), "p99_ms": round(float(np.percentile(lat, 99)), 1),
               "max_ms": round(float(lat.max()), 1)}
    finally:
        server.stop()
    return out


def outage_events(container: str, t_down: float, t_up: float, log: list, mode: str = "stop"):
    """mode "stop": container stopped (connections refused / reset); mode "pause": container frozen
    (cgroup freezer) - TCP connects succeed but nothing is ever answered, i.e. a network black hole."""
    down_cmd = ["docker", "stop", "-t", "1", container] if mode == "stop" else ["docker", "pause", container]
    up_cmd = ["docker", "start", container] if mode == "stop" else ["docker", "unpause", container]

    def down():
        log.append(("fault_issued", time.time()))
        subprocess.run(down_cmd, capture_output=True)
        log.append(("fault_done", time.time()))

    def up():
        log.append(("recover_issued", time.time()))
        subprocess.run(up_cmd, capture_output=True)
        log.append(("recover_done", time.time()))
    return [(t_down, down), (t_up, up)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--rates", default="100")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--duration", type=float, default=20)
    ap.add_argument("--warmup", type=float, default=5)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--timeline", action="store_true")
    ap.add_argument("--stampede-n", type=int, default=200)
    ap.add_argument("--env", action="append", default=[], help="server env KEY=VAL")
    ap.add_argument("--tag", default="")
    ap.add_argument("--outage-container", default=None)
    ap.add_argument("--outage-mode", default=None, choices=["stop", "pause"])
    ap.add_argument("--rep-offset", type=int, default=0, help="added to the repetition index (interleaved A/B runs)")
    ap.add_argument("--outage-down", type=float, default=15)
    ap.add_argument("--outage-up", type=float, default=40)
    args = ap.parse_args()
    extra_env = dict(e.split("=", 1) for e in args.env)
    out_dir = RESULTS / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    C.save_json(out_dir / "environment.json", C.environment_metadata(Path(args.code)))
    path = out_dir / f"{args.scenario}{('_' + args.tag) if args.tag else ''}.json"
    existing = json.loads(path.read_text()) if path.exists() else []
    runs = []
    if args.scenario == "stampede":
        for rep in range(args.reps):
            r = stampede(args, rep + args.rep_offset); runs.append(r); print(json.dumps(r))
    else:
        for rate in [float(x) for x in args.rates.split(",")]:
            for rep in range(args.reps):
                events_fn, log = None, []
                if args.scenario in ("outage", "pgoutage"):
                    args.timeline = True
                    cont = args.outage_container or ("taxbench-postgres" if args.scenario == "pgoutage" else "taxbench-redis-b")
                    mode = args.outage_mode or ("pause" if args.scenario == "pgoutage" else "stop")
                    events_fn = lambda: outage_events(cont, args.outage_down, args.outage_up, log, mode)  # noqa: E731
                r = run_point(args, args.scenario, rate, rep + args.rep_offset, extra_env, events_fn, args.tag)
                if log:
                    r["outage_log"] = log
                    for c in ("taxbench-redis-b", "taxbench-postgres"):   # always leave the stack healthy
                        subprocess.run(["docker", "unpause", c], capture_output=True)
                        subprocess.run(["docker", "start", c], capture_output=True)
                runs.append(r)
                s = r["summary"]
                print(f"[{args.label}/{args.scenario}] rate={rate:g} rep={rep} ok_rps={s['achieved_ok_rps']} "
                      f"p50={s['p50_ms']} p95={s['p95_ms']} p99={s['p99_ms']} err={s['error_rate']} "
                      f"hit={r['redis_hit_rate_pct']} cpu={r['resources'].get('server_cpu_pct_mean')} "
                      f"lagp99={s['send_lag_p99_ms']}", flush=True)
    C.save_json(path, existing + runs)


if __name__ == "__main__":
    main()
