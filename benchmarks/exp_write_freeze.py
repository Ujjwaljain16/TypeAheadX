"""Experiment: write path while PostgreSQL is frozen (docker pause), then recovers.

Floods POST /search with unique queries while the database is unresponsive, then unpauses it.
Reports accepted vs rejected requests, the server's peak RSS, how many accepted events were
ultimately persisted, and the drain time.

  python benchmarks/exp_write_freeze.py --code <checkout> --label baseline --events 150000
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
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

PFX = "freezeprobe"


async def flood(n: int, conc: int):
    ok = bad = 0
    sem = asyncio.Semaphore(conc)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=conc), timeout=aiohttp.ClientTimeout(total=60)) as s:
        async def one(i):
            nonlocal ok, bad
            async with sem:
                try:
                    async with s.post(C.BASE_URL + "/search", json={"query": f"{PFX} {i:07d}"}) as r:
                        await r.read()
                        if r.status == 200:
                            ok += 1
                        else:
                            bad += 1
                except Exception:
                    bad += 1
        await asyncio.gather(*[one(i) for i in range(n)])
    return ok, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--events", type=int, default=150_000)
    ap.add_argument("--concurrency", type=int, default=100)
    ap.add_argument("--drain-timeout", type=float, default=900)
    a = ap.parse_args()
    out_dir = C.REPO / "benchmarks" / "results" / "experiments"
    out_dir.mkdir(parents=True, exist_ok=True)
    with C.pg_conn() as c:
        c.execute("DELETE FROM queries WHERE query LIKE %s", (PFX + "%",))
    srv = C.Server(Path(a.code), log_path=out_dir / f"server_writefreeze_{a.label}.log")
    srv.start()
    res = {"label": a.label, "code": a.code, "events_sent": a.events}
    try:
        import requests
        requests.post(C.BASE_URL + "/search", json={"query": PFX + " warm"}); time.sleep(12)   # one real flush => pooled connection
        real = [c for c in srv.tree() if c.pid != srv.proc.pid] or [psutil.Process(srv.proc.pid)]   # skip the venv launcher stub
        proc = real[0]
        rss0 = proc.memory_info().rss
        subprocess.run(["docker", "pause", "taxbench-postgres"], capture_output=True)
        t0 = time.time()
        ok, bad = asyncio.run(flood(a.events, a.concurrency))
        res.update(accepted_200=ok, rejected_or_failed=bad, flood_seconds=round(time.time() - t0, 1))
        time.sleep(15)                                                   # let flush attempts pile up while frozen
        rss_peak = proc.memory_info().rss
        wm = requests.get(C.BASE_URL + "/write/metrics", timeout=5).json()
        res.update(rss_before_mb=round(rss0 / 2**20, 1), rss_during_freeze_mb=round(rss_peak / 2**20, 1),
                   buffer_unique_during_freeze=wm["buffer_current_size"], metrics_during_freeze=wm)
        subprocess.run(["docker", "unpause", "taxbench-postgres"], capture_output=True)
        t1 = time.time()
        # Drain = persisted-event count stops changing AND the buffer is empty. (Buffer size alone is NOT enough: the
        # worker swaps the buffer out before the slow write, so size 0 can mean "write still in flight".)
        last, stable_since = -1, time.time()
        while time.time() - t1 < a.drain_timeout:
            wm = requests.get(C.BASE_URL + "/write/metrics", timeout=30).json()
            with C.pg_conn() as c:
                cur = int(c.execute("SELECT coalesce(sum(historical_count),0) FROM queries WHERE query LIKE %s AND query <> %s",
                                    (PFX + "%", PFX + " warm")).fetchone()[0])
            if cur != last:
                last, stable_since = cur, time.time()
            if wm["buffer_current_size"] == 0 and time.time() - stable_since > 15 and cur > 0:
                break
            time.sleep(2)
        res["drain_seconds_after_unfreeze"] = round(time.time() - t1 - 15, 1)
        with C.pg_conn() as c:
            persisted = c.execute("SELECT count(*), coalesce(sum(historical_count),0) FROM queries WHERE query LIKE %s AND query <> %s",
                                  (PFX + "%", PFX + " warm")).fetchone()
        res.update(persisted_rows=persisted[0], persisted_events=int(persisted[1]),
                   accepted_but_not_persisted=ok - int(persisted[1]), final_metrics=requests.get(C.BASE_URL + "/write/metrics", timeout=5).json())
    finally:
        subprocess.run(["docker", "unpause", "taxbench-postgres"], capture_output=True)
        srv.stop()
        with C.pg_conn() as c:
            c.execute("DELETE FROM queries WHERE query LIKE %s", (PFX + "%",))
    print(json.dumps(res))
    with open(out_dir / "write_freeze.jsonl", "a") as fh:
        fh.write(json.dumps(res) + "\n")


if __name__ == "__main__":
    main()
