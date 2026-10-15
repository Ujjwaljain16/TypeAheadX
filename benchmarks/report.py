"""Aggregate benchmark JSON/raw files into Markdown tables + CSV.

  python benchmarks/report.py --labels baseline final --out audit/results/summary
Uncertainty: per (label, scenario, rate) we show the median and min-max over repetitions, and a
95% block-bootstrap CI (1-second blocks, 1000 resamples, pooled over repetitions) for p50 and p99
computed from the raw per-request files.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
RES = REPO / "audit" / "results"


def load_raw(rel: str):
    t, lat, ok = [], [], []
    with gzip.open(REPO / rel, "rt") as fh:
        next(fh)
        for line in fh:
            a, b, c, _ = line.rstrip("\n").split(",")
            t.append(float(a)); lat.append(float(b)); ok.append(c.startswith("2"))
    return np.asarray(t), np.asarray(lat), np.asarray(ok)


def block_bootstrap_ci(runs: list[tuple], qs=(50, 99), n_boot=1000, seed=7):
    """runs: list of (t, lat, ok). Blocks = (run index, whole second). Returns {q: (lo, hi)} on OK latencies."""
    blocks = []
    for ri, (t, lat, ok) in enumerate(runs):
        sec = np.floor(t).astype(int)
        for s in np.unique(sec):
            m = (sec == s) & ok
            if m.any():
                blocks.append(lat[m])
    if len(blocks) < 5:
        return {q: (None, None) for q in qs}
    rng = np.random.default_rng(seed)
    out = {q: [] for q in qs}
    for _ in range(n_boot):
        idx = rng.integers(0, len(blocks), size=len(blocks))
        pooled = np.concatenate([blocks[i] for i in idx])
        for q in qs:
            out[q].append(np.percentile(pooled, q))
    return {q: (round(float(np.percentile(v, 2.5)), 2), round(float(np.percentile(v, 97.5)), 2)) for q, v in out.items()}


def fmt(x, nd=1):
    return "–" if x is None else f"{x:.{nd}f}"


def collect(label: str):
    d = RES / label
    data = defaultdict(lambda: defaultdict(list))   # scenario(tag) -> rate -> [run]
    for f in sorted(d.glob("*.json")):
        if f.name == "environment.json":
            continue
        for r in json.loads(f.read_text()):
            if r.get("scenario") == "stampede":
                data["stampede"][0].append(r)
            else:
                key = r["scenario"] + (f"[{r['tag']}]" if r.get("tag") else "") + f"/w{r.get('workers', 1)}"
                data[key][r["rate"]].append(r)
    return data


def agg(runs):
    s = [r["summary"] for r in runs]
    def med(k):
        v = [x[k] for x in s if x.get(k) is not None]
        return st.median(v) if v else None
    def rng(k):
        v = [x[k] for x in s if x.get(k) is not None]
        return (min(v), max(v)) if v else (None, None)
    hit = [r["redis_hit_rate_pct"] for r in runs if r.get("redis_hit_rate_pct") is not None]
    cpu = [r["resources"].get("server_cpu_pct_mean") for r in runs if r.get("resources")]
    return {
        "n_runs": len(runs), "samples": sum(x["n_latency_samples"] for x in s),
        "ok_rps": med("achieved_ok_rps"), "err": max(x["error_rate"] for x in s),
        "p50": med("p50_ms"), "p50r": rng("p50_ms"), "p95": med("p95_ms"),
        "p99": med("p99_ms"), "p99r": rng("p99_ms"), "max": max((x["max_ms"] or 0) for x in s),
        "hit": st.median(hit) if hit else None, "cpu": st.median([c for c in cpu if c is not None]) if cpu else None,
        "lag99": max((x["send_lag_p99_ms"] or 0) for x in s),
    }


def table(label: str, scenario: str, rates: dict, with_ci: bool) -> list[str]:
    lines = [f"**{label} — {scenario}**", "",
             "| offered rps | runs | samples | ok rps | err rate | p50 ms (min–max) | p95 ms | p99 ms (min–max) | max ms | "
             + ("p50 CI95 | p99 CI95 | " if with_ci else "") + "Redis hit % | server CPU % | gen lag p99 ms |",
             "|---:|---:|---:|---:|---:|---|---:|---|---:|" + ("---|---|" if with_ci else "") + "---:|---:|---:|"]
    for rate in sorted(rates):
        runs = rates[rate]
        a = agg(runs)
        ci = ("", "")
        if with_ci:
            raws = [load_raw(r["raw_file"]) for r in runs if r.get("raw_file")]
            c = block_bootstrap_ci(raws) if raws else {50: (None, None), 99: (None, None)}
            ci = (f"{fmt(c[50][0])}–{fmt(c[50][1])}", f"{fmt(c[99][0])}–{fmt(c[99][1])}")
        lines.append(
            f"| {rate:g} | {a['n_runs']} | {a['samples']} | {fmt(a['ok_rps'])} | {a['err']:.3f} | "
            f"{fmt(a['p50'],2)} ({fmt(a['p50r'][0],2)}–{fmt(a['p50r'][1],2)}) | {fmt(a['p95'])} | "
            f"{fmt(a['p99'])} ({fmt(a['p99r'][0])}–{fmt(a['p99r'][1])}) | {fmt(a['max'],0)} | "
            + (f"{ci[0]} | {ci[1]} | " if with_ci else "")
            + f"{fmt(a['hit'])} | {fmt(a['cpu'])} | {fmt(a['lag99'])} |")
    return lines + [""]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", nargs="+", required=True)
    ap.add_argument("--out", default=str(RES / "summary"))
    ap.add_argument("--ci", action="store_true")
    ap.add_argument("--scenarios", nargs="*")
    args = ap.parse_args()
    md, rows = [], []
    for label in args.labels:
        data = collect(label)
        for scen in sorted(data):
            if args.scenarios and scen.split("/")[0].split("[")[0] not in args.scenarios:
                continue
            if scen == "stampede":
                md += [f"**{label} — stampede (200 simultaneous identical misses x 20 keys)**", "",
                       "| rep | requests | DB transactions | per key (ideal 1) | p50 ms | p99 ms | max ms |", "|---:|---:|---:|---:|---:|---:|---:|"]
                for r in data[scen][0]:
                    md.append(f"| {r['rep']} | {r['total_requests']} | {r['db_xacts_during_burst']} | {r['db_queries_per_key']} | {r['p50_ms']} | {r['p99_ms']} | {r['max_ms']} |")
                md.append("")
                continue
            md += table(label, scen, data[scen], args.ci)
            for rate, runs in sorted(data[scen].items()):
                a = agg(runs)
                rows.append({"label": label, "scenario": scen, "rate": rate, **{k: v for k, v in a.items() if not k.endswith("r")}})
    Path(args.out + ".md").write_text("\n".join(md), encoding="utf-8")
    if rows:
        with open(args.out + ".csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
    print("\n".join(md))


if __name__ == "__main__":
    main()
