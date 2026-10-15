#!/usr/bin/env bash
# Headline comparison: every scenario, baseline vs final, INTERLEAVED per repetition (see run_ab.sh).
# usage: benchmarks/run_matrix_ab.sh <baseline_checkout> <final_checkout>
set -u
B="$1"; F="$2"
cd "$(dirname "$0")/.."
AB="bash benchmarks/run_ab.sh"
V="baseline=$B final=$F"
$AB warm      100,200,300,400,500,600 3 20 5  ab $V
$AB cold      25,50,100,150           3 20 3  ab $V
$AB mixed     50,100,150,200,300      3 25 15 ab $V
$AB highcard  50,100,150,200          3 20 5  ab $V
$AB popular   100,200,300,400         3 20 5  ab $V
$AB zipf      100,200,300             3 20 10 ab $V
$AB rw        100,200,300             3 20 10 ab $V
$AB pgonly    50,100,200,300,400      3 20 5  ab $V
$AB stampede  100                     5 20 5  ab $V
$AB outage    100                     2 50 5  ab $V -- --outage-down 15 --outage-up 35 --timeline
$AB outage    100                     2 50 5  ab $V -- --outage-down 15 --outage-up 35 --outage-mode pause --tag pause --timeline
$AB pgoutage  60                      2 60 15 ab $V -- --outage-down 30 --outage-up 50 --timeline
$AB burst     100                     3 40 5  ab $V
$AB sustained 120                     1 120 10 ab $V
echo "MATRIX AB DONE"
