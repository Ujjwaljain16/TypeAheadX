#!/usr/bin/env bash
# Full benchmark matrix. Usage: benchmarks/run_matrix.sh <code_dir> <label> [quick]
# Run against a quiet machine; do not run other CPU-heavy work concurrently.
set -u
CODE="$1"; LABEL="$2"; MODE="${3:-full}"
cd "$(dirname "$0")/.."
source benchmarks/env.sh
PY="${PY:-./.venv/Scripts/python}"
RB="$PY benchmarks/run_bench.py --code $CODE --label $LABEL"
REPS=3; [ "$MODE" = "quick" ] && REPS=1
$RB --scenario warm      --rates 50,100,150,200,250,300 --reps $REPS --duration 20 --warmup 5
$RB --scenario cold      --rates 25,50,100,150          --reps $REPS --duration 20 --warmup 3
$RB --scenario mixed     --rates 50,100,150,200         --reps $REPS --duration 25 --warmup 15
$RB --scenario highcard  --rates 50,100,150             --reps $REPS --duration 20 --warmup 5
$RB --scenario popular   --rates 100,200,300            --reps $REPS --duration 20 --warmup 5
$RB --scenario zipf      --rates 100,200                --reps $REPS --duration 20 --warmup 10
$RB --scenario rw        --rates 100,200                --reps $REPS --duration 20 --warmup 10
$RB --scenario pgonly    --rates 25,50,100,150          --reps $REPS --duration 20 --warmup 5
$RB --scenario stampede  --reps $REPS
$RB --scenario outage    --rates 100 --reps $([ "$MODE" = "quick" ] && echo 1 || echo 2) --duration 50 --warmup 5 --outage-down 15 --outage-up 35 --timeline
$RB --scenario burst     --rates 100 --reps $REPS --duration 40 --warmup 5
$RB --scenario sustained --rates 120 --reps 1 --duration 180 --warmup 10
echo "MATRIX DONE $LABEL"
