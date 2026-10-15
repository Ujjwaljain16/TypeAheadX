"""Checks several quantitative claims made in README.md / docs/*.md against the actual code.

Pure computation (no services). Prints JSON; also appended to benchmarks/results/experiments/claims.json.
  python benchmarks/exp_claims.py
"""
from __future__ import annotations

import json
import math
import random
import string
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
from app.cache.consistent_hash_ring import ConsistentHashRing  # noqa: E402

res: dict = {}

# --- 1. Key ownership of the ring with the documented configuration (3 nodes, 500 vnodes) ---------
MAXH = 2 ** 128
for vn in (150, 500):
    r = ConsistentHashRing(vn)
    for n in ("redis-a", "redis-b", "redis-c"):
        r.add_node(n)
    own = Counter()
    for i, h in enumerate(r.ring):
        prev = r.ring[i - 1] if i else r.ring[-1]
        arc = h - prev if h > prev else MAXH - prev + h
        own[r.positions[h].physical_node] += arc
    share = {k: round(100 * v / MAXH, 2) for k, v in sorted(own.items())}
    res[f"ownership_{vn}_vnodes_pct"] = share
    res[f"ownership_{vn}_max_abs_dev_from_33.33_pts"] = round(max(abs(v - 100 / 3) for v in share.values()), 2)

# --- 2. Key movement when adding a 4th node ------------------------------------------------------
rng = random.Random(1)
keys = list({"suggestion:" + "".join(rng.choices(string.ascii_lowercase, k=rng.randint(4, 10))) for _ in range(100_000)})
r3 = ConsistentHashRing(500); [r3.add_node(n) for n in ("redis-a", "redis-b", "redis-c")]
r4 = ConsistentHashRing(500); [r4.add_node(n) for n in ("redis-a", "redis-b", "redis-c", "redis-d")]
moved = sum(r3.get_node(k).physical_node != r4.get_node(k).physical_node for k in keys)
res["keys_moved_adding_4th_node_pct"] = round(100 * moved / len(keys), 2)
res["ideal_pct"] = 25.0

# --- 3. The 'hot shard' explanation: reproduce scripts/final_benchmark.py's workload --------------
top = ["iphone 16", "chatgpt", "samsung galaxy s24", "macbook pro m3", "python tutorial", "fastapi react tutorial",
       "aws certifications", "docker vs kubernetes", "redis consistent hashing", "system design interview"]
pool = top + [f"query_item_{i}" for i in range(len(top), 10_000)]
ring = r3
node_share_runs, top1_share_runs, hit_cap_runs = [], [], []
for seed in range(20):
    nrng = np.random.default_rng(seed)
    ranks = np.clip(nrng.zipf(a=1.3, size=100_000), 1, 10_000)
    c = Counter(pool[x - 1] for x in ranks)
    per_node = Counter()
    for q, n in c.items():
        per_node[ring.get_node("suggestion:" + q).physical_node] += n
    node_share_runs.append({k: round(100 * v / 100_000, 1) for k, v in sorted(per_node.items())})
    top1_share_runs.append(round(100 * c.most_common(1)[0][1] / 100_000, 1))
    hit_cap_runs.append(round(100 * (1 - len(c) / 100_000), 1))
res["final_benchmark_workload"] = {
    "note": "np.random.zipf(a=1.3) clipped to 10k ranks, queries 'query_item_N' (NOT in the dataset), 20 seeds",
    "request_share_per_node_pct_by_seed": node_share_runs[:6],
    "node_with_max_share_range_pct": [max(max(d.values()) for d in node_share_runs), min(max(d.values()) for d in node_share_runs)],
    "top1_query_share_pct_range": [min(top1_share_runs), max(top1_share_runs)],
    "distinct_keys_range": None,
    "max_possible_hit_rate_pct_of_a_cold_cache_range": [min(hit_cap_runs), max(hit_cap_runs)],
}
res["interpretation"] = ("A single key ('iphone 16' = rank 1) receives roughly a quarter to a third of all requests under this synthetic "
                         "Zipf(1.3); whichever node owns that key gets that share on top of ~1/3 of the rest. That is a property of the "
                         "workload, not of the hash ring, and the 10 000 distinct synthetic keys cap the miss count regardless of cache design.")

# --- 4. Closed-loop 'concurrency' of scripts/final_benchmark.py -----------------------------------
res["final_benchmark_concurrency"] = ("requests are sent in chunks of 100 with asyncio.gather and the next chunk starts only when the "
                                      "whole chunk finished (closed loop); in-flight requests never exceed 100, not 100 000, and latency "
                                      "excludes queueing that open-loop arrivals would incur")

print(json.dumps(res, indent=2))
out = REPO / "benchmarks" / "results" / "experiments"
out.mkdir(parents=True, exist_ok=True)
(out / "claims.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
