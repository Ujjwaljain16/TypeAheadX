"""Experiment: wall time of one BatchWorker.flush() (DB write + cache invalidation) for 100 distinct queries.

Runs the application's own singletons against real PostgreSQL and the real 3-node Redis ring, in a
child process per code version (so each version imports its own code).

  python benchmarks/exp_flush_duration.py --code <checkout> --label baseline --rounds 30
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

CHILD = r'''
import os, sys, time, json, random, string
sys.path.insert(0, os.path.join(sys.argv[1], "backend"))
from app.write_buffer.buffer import write_buffer
from app.write_buffer.batch_worker import batch_worker
from app.cache.factory import CacheFactory
rounds, per = int(sys.argv[2]), 100
CacheFactory.get_cache()
rnd = random.Random(42)
words = ["".join(rnd.choices(string.ascii_lowercase, k=rnd.randint(3, 9))) for _ in range(5000)]
times = []
for r in range(rounds + 3):
    for i in range(per):
        q = " ".join(rnd.choices(words, k=rnd.randint(2, 3)))
        write_buffer.increment(q)
    t = time.perf_counter(); batch_worker.flush(); dt = (time.perf_counter() - t) * 1000
    if r >= 3:                                  # first three rounds are warm-up (connections)
        times.append(dt)
times.sort()
print(json.dumps({"rounds": len(times), "median_ms": round(times[len(times)//2], 1), "p95_ms": round(times[int(len(times)*0.95)-1], 1), "min_ms": round(times[0], 1), "max_ms": round(times[-1], 1)}))
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--rounds", type=int, default=30)
    a = ap.parse_args()
    C.flush_redis()
    p = subprocess.run([sys.executable, "-c", CHILD, a.code, str(a.rounds)], env=C.bench_env(), capture_output=True, text=True,
                       cwd=str(Path(a.code) / "backend"))
    last = [l for l in p.stdout.splitlines() if l.startswith("{")]
    if not last:
        print(p.stdout[-500:], p.stderr[-800:])
        raise SystemExit(1)
    res = {"label": a.label, "code": a.code, **json.loads(last[-1])}
    print(json.dumps(res))
    out = C.REPO / "benchmarks" / "results" / "experiments"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "flush_duration.jsonl", "a") as fh:
        fh.write(json.dumps(res) + "\n")


if __name__ == "__main__":
    main()
