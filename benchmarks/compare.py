"""Compact before/after table from two result labels (medians over repetitions)."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import report as R

def main(a, b, out):
    da, db = R.collect(a), R.collect(b)
    lines = ["| scenario | offered rps | p50 ms base → final | p99 ms base → final | ok rps base → final | err base → final | API CPU % base → final | hit % base → final |",
             "|---|---:|---|---|---|---|---|---|"]
    for scen in sorted(da):
        if scen == "stampede" or scen not in db:
            continue
        for rate in sorted(da[scen]):
            if rate not in db[scen]:
                continue
            x, y = R.agg(da[scen][rate]), R.agg(db[scen][rate])
            def ch(u, v):
                return "" if not u or v is None else f" ({100*(v-u)/u:+.0f}%)"
            lines.append(f"| {scen.split('/')[0]} | {rate:g} | {R.fmt(x['p50'],2)} → {R.fmt(y['p50'],2)}{ch(x['p50'],y['p50'])} | "
                         f"{R.fmt(x['p99'],1)} → {R.fmt(y['p99'],1)}{ch(x['p99'],y['p99'])} | {R.fmt(x['ok_rps'],0)} → {R.fmt(y['ok_rps'],0)} | "
                         f"{x['err']:.3f} → {y['err']:.3f} | {R.fmt(x['cpu'],0)} → {R.fmt(y['cpu'],0)}{ch(x['cpu'],y['cpu'])} | {R.fmt(x['hit'],0)} → {R.fmt(y['hit'],0)} |")
    Path(out).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
