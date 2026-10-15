#!/usr/bin/env bash
# Linux / multi-worker benchmark for a shared CI runner (see .github/workflows/benchmark.yml).
# Interleaved baseline-vs-current per repetition, like run_matrix_ab.sh, but only scenarios that need no docker
# fault injection. Usage: benchmarks/ci_matrix.sh <baseline_checkout> <current_checkout>
set -u
B="$1"; F="$2"
cd "$(dirname "$0")/.."
AB="bash benchmarks/run_ab.sh"
V="baseline=$B final=$F"
# 1 worker: hit-path sweep, mixed cache hit/miss, DB-only path, stampede
$AB warm     200,500,900,1300 3 15 4 lx1 $V -- --workers 1
$AB mixed    200,500          3 15 8 lx1 $V -- --workers 1
$AB pgonly   200,500          3 15 4 lx1 $V -- --workers 1
$AB stampede 100              3 15 4 lx1 $V -- --workers 1
# 2 workers: does the hit path scale with processes? (generator shares the 4 vCPUs, so treat as indicative)
$AB warm     900,1500,2200    3 15 4 lx2 $V -- --workers 2
echo "CI MATRIX DONE"
