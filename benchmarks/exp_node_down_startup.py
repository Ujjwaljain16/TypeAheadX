"""Experiment: a Redis node that is down while the API starts - is it ever used again after it recovers?

1. stop redis-b, 2. start the API, 3. start redis-b, 4. send repeated requests for keys that hash to
redis-b and look at redis-b's own keyspace hit counter.

  python benchmarks/exp_node_down_startup.py --code <checkout> --label baseline
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    subprocess.run(["docker", "stop", "-t", "1", "taxaudit-redis-b"], capture_output=True)
    C.flush_redis()
    srv = C.Server(Path(a.code), log_path=C.REPO / "audit" / "results" / "experiments" / f"server_nodedown_{a.label}.log")
    (C.REPO / "audit" / "results" / "experiments").mkdir(parents=True, exist_ok=True)
    try:
        srv.start()
        subprocess.run(["docker", "start", "taxaudit-redis-b"], capture_output=True)
        time.sleep(12)                       # > breaker window (5 s * 1.2), so a recovering design has had time
        C.flush_redis()
        # find prefixes owned by redis-b (port 47380 => name "localhost:47380") using the app's own routing
        sys.path.insert(0, str(Path(a.code) / "backend"))
        import os
        os.environ.update(C.audit_env())
        from app.cache.consistent_hash_ring import ConsistentHashRing
        ring = ConsistentHashRing(500)
        for p in C.REDIS_PORTS:
            ring.add_node(f"localhost:{p}")
        owned = [k for k in (f"ab{i}" for i in range(3000)) if ring.get_node(f"suggestion:{k}").physical_node == f"localhost:{C.REDIS_PORTS[1]}"][:50]
        b = C.redis_clients()[1]
        before = b.info("stats")["keyspace_hits"]
        for _ in range(3):
            for k in owned:
                requests.get(C.BASE_URL + "/suggest", params={"q": k}, timeout=5)
        after = b.info("stats")["keyspace_hits"]
        keys_on_b = b.dbsize()
        res = {"label": a.label, "code": a.code, "keys_probed": len(owned), "requests": 3 * len(owned),
               "redis_b_keyspace_hits_delta": after - before, "redis_b_dbsize_after": keys_on_b,
               "recovered_and_used": keys_on_b > 0}
        print(json.dumps(res))
        with open(C.REPO / "audit" / "results" / "experiments" / "node_down_startup.jsonl", "a") as fh:
            fh.write(json.dumps(res) + "\n")
    finally:
        srv.stop()
        subprocess.run(["docker", "start", "taxaudit-redis-b"], capture_output=True)


if __name__ == "__main__":
    main()
