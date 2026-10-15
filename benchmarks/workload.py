"""Deterministic workload generation for TypeAheadX benchmarks.

Provenance of the data (be honest about what is real vs. synthetic):

* REAL:       the query strings and their ``historical_count`` values come from
              ``data/processed/queries.csv`` (AmazonQAC-derived, per data/README.md).
              These are *selection counts*, not a request log.
* SYNTHETIC:  everything about *how users type* (keystroke cascades, stop
              positions, interleaving, read/write mix) and the pure Zipf profile.
              No production request log is available, so request-level
              realism is NOT claimed.

All generators are pure functions of (dataset, seed, parameters).
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "processed" / "queries.csv"
MAX_PREFIX = 64


def load_dataset(path: Path | str = DEFAULT_CSV) -> tuple[list[str], np.ndarray]:
    queries: list[str] = []
    counts: list[int] = []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        next(reader)  # header
        for row in reader:
            queries.append(row[0])
            counts.append(int(row[1]))
    return queries, np.asarray(counts, dtype=np.float64)


def _sampler(counts: np.ndarray, rng: np.random.Generator, n: int) -> np.ndarray:
    p = counts / counts.sum()
    return rng.choice(len(counts), size=n, p=p)


def cascade_stream(queries, counts, n_requests: int, seed: int, interleave: int = 8) -> list[str]:
    """Typing cascades: sample a target query proportional to its dataset count,
    the user types it character by character and stops after a random point
    (uniform in [min(3,len), len]). ``interleave`` sessions are typed concurrently
    (round-robin), approximating many simultaneous users. Prefixes are emitted
    exactly as a client would send them (already lowercase in this dataset)."""
    rng = np.random.default_rng(seed)
    out: list[str] = []
    sessions: list[list[str]] = []
    while len(out) < n_requests:
        while len(sessions) < interleave:
            q = queries[int(_sampler(counts, rng, 1)[0])]
            stop = int(rng.integers(min(3, len(q)), len(q) + 1))
            sessions.append([q[:i] for i in range(1, stop + 1)])
        # round-robin one keystroke from each live session
        nxt = []
        for s in sessions:
            out.append(s.pop(0))
            if s:
                nxt.append(s)
        sessions = nxt
    return out[:n_requests]


def uniform_prefix_stream(queries, n_requests: int, seed: int) -> list[str]:
    """High-cardinality / poor reuse: uniformly random query, uniformly random
    prefix length >= 2. Almost every request is a distinct key."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(queries), size=n_requests)
    out = []
    for i in idx:
        q = queries[int(i)]
        out.append(q[: int(rng.integers(min(2, len(q)), len(q) + 1))])
    return out


def popular_stream(queries, counts, n_requests: int, seed: int, top_prefixes: int = 100) -> list[str]:
    """Heavy reuse: only the ``top_prefixes`` most popular prefixes (ranked by
    summed dataset count of queries beginning with them), sampled by that weight."""
    weight: dict[str, float] = {}
    for q, c in zip(queries, counts):
        for i in range(1, min(len(q), MAX_PREFIX) + 1):
            weight[q[:i]] = weight.get(q[:i], 0.0) + c
    top = sorted(weight.items(), key=lambda kv: -kv[1])[:top_prefixes]
    prefixes = [p for p, _ in top]
    w = np.asarray([v for _, v in top])
    rng = np.random.default_rng(seed)
    return [prefixes[i] for i in rng.choice(len(prefixes), size=n_requests, p=w / w.sum())]


def zipf_stream(queries, counts, n_requests: int, seed: int, alpha: float = 1.1, pool: int = 50_000) -> list[str]:
    """Pure synthetic Zipf over a pool of prefixes (ranked by dataset-derived weight)."""
    weight: dict[str, float] = {}
    for q, c in zip(queries, counts):
        for i in range(2, min(len(q), MAX_PREFIX) + 1):
            weight[q[:i]] = weight.get(q[:i], 0.0) + c
    ranked = [p for p, _ in sorted(weight.items(), key=lambda kv: -kv[1])[:pool]]
    ranks = np.arange(1, len(ranked) + 1, dtype=np.float64)
    p = ranks ** (-alpha)
    rng = np.random.default_rng(seed)
    return [ranked[i] for i in rng.choice(len(ranked), size=n_requests, p=p / p.sum())]


def distinct_keys(stream: list[str]) -> int:
    return len(set(stream))


def stream_stats(stream: list[str]) -> dict:
    from collections import Counter

    c = Counter(stream)
    top = c.most_common(1)[0]
    return {
        "requests": len(stream),
        "distinct_prefixes": len(c),
        "top1_prefix": top[0],
        "top1_share": round(top[1] / len(stream), 4),
        "ideal_hit_rate_infinite_cache": round(1 - len(c) / len(stream), 4),
    }
