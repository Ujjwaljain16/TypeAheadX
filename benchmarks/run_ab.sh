#!/usr/bin/env bash
# Interleaved A/B comparison: for every repetition, run each variant back-to-back so that slow drift of
# the (shared, non-isolated) machine hits all variants equally.
# usage: run_ab.sh <scenario> <rates> <reps> <duration> <warmup> <label_prefix> name=checkout_dir ... [-- extra run_bench args]
set -u
SCEN="$1"; RATES="$2"; REPS="$3"; DUR="$4"; WARM="$5"; PFX="$6"; shift 6
VARS=(); EXTRA=()
while [ $# -gt 0 ]; do
  if [ "$1" = "--" ]; then shift; EXTRA=("$@"); break; fi
  VARS+=("$1"); shift
done
cd "$(dirname "$0")/.."
source benchmarks/env.sh
for ((r=0; r<REPS; r++)); do
  for v in "${VARS[@]}"; do
    name="${v%%=*}"; dir="${v#*=}"
    ./.venv/Scripts/python benchmarks/run_bench.py --code "$dir" --label "${PFX}_${name}" --scenario "$SCEN" \
      --rates "$RATES" --reps 1 --rep-offset $r --duration "$DUR" --warmup "$WARM" "${EXTRA[@]}"
  done
done
echo "AB DONE $SCEN"
