"""Experiment: do concurrent flushers (several API workers / pods) lose updates?

K OS processes each record N searches for the same query and flush M times through the
application's own `write_buffer` / `batch_worker` singletons, against a REAL PostgreSQL.
Expected final historical_count = K * M * N exactly if no update is lost.

  python benchmarks/exp_lost_update.py --code <checkout> [--procs 6] [--rounds 40] [--per-round 3]
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

QUERY = "lost update probe"


def worker(code_dir: str, rounds: int, per_round: int, barrier, out):
    os.environ.update(C.audit_env())
    sys.path.insert(0, str(Path(code_dir) / "backend"))
    from app.write_buffer.buffer import write_buffer
    from app.write_buffer.batch_worker import batch_worker
    barrier.wait()
    for _ in range(rounds):
        for _ in range(per_round):
            write_buffer.increment(QUERY)
        batch_worker.flush()
    out.put(os.getpid())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--rounds", type=int, default=40)
    ap.add_argument("--per-round", type=int, default=3)
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    with C.pg_conn() as c:
        c.execute("DELETE FROM queries WHERE query = %s", (QUERY,))
    barrier, q = mp.Barrier(a.procs), mp.Queue()
    ps = [mp.Process(target=worker, args=(a.code, a.rounds, a.per_round, barrier, q)) for _ in range(a.procs)]
    t0 = time.time()
    [p.start() for p in ps]
    [p.join() for p in ps]
    with C.pg_conn() as c:
        row = c.execute("SELECT historical_count, recent_count FROM queries WHERE query = %s", (QUERY,)).fetchone()
        c.execute("DELETE FROM queries WHERE query = %s", (QUERY,))
    expected = a.procs * a.rounds * a.per_round
    got = row[0] if row else 0
    res = {"code": a.code, "label": a.label, "processes": a.procs, "rounds_each": a.rounds, "events_per_round": a.per_round,
           "expected_historical_count": expected, "actual_historical_count": got,
           "lost_events": expected - got, "lost_pct": round(100 * (expected - got) / expected, 2),
           "seconds": round(time.time() - t0, 1)}
    print(json.dumps(res))
    out = C.REPO / "audit" / "results" / "experiments"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "lost_update.jsonl", "a") as fh:
        fh.write(json.dumps(res) + "\n")


if __name__ == "__main__":
    main()
