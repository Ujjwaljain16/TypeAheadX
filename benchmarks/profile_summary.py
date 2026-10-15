"""Summarise a py-spy raw (collapsed-stack) file recorded with --gil: inclusive and self share per function."""
import sys, collections, re
tot = 0
incl, selfc = collections.Counter(), collections.Counter()
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    stack, _, n = line.rpartition(" ")
    n = int(n); tot += n
    frames = stack.split(";")
    seen = set()
    for f in frames:
        key = re.sub(r"\s*\(([^)]*[\/])?([^\/)]+)\)", r" (\2)", f)   # keep file basename only
        if key not in seen:
            incl[key] += n; seen.add(key)
    selfc[re.sub(r"\s*\(([^)]*[\/])?([^\/)]+)\)", r" (\2)", frames[-1])] += n
top = int(sys.argv[2]) if len(sys.argv) > 2 else 25
print(f"GIL-holding samples: {tot}")
print("\n== inclusive (% of GIL time) ==")
for k, v in incl.most_common(top): print(f"{100*v/tot:5.1f}%  {k}")
print("\n== self (leaf) ==")
for k, v in selfc.most_common(top): print(f"{100*v/tot:5.1f}%  {k}")
