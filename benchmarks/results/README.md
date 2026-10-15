# Measurement data

Machine-readable results. Each directory is a *label* (one code variant × one session); each `<scenario>.json` holds one entry per (rate × repetition): summary percentiles, throughput, error rate, status counts, API CPU/RSS, Redis and PostgreSQL counter deltas, per-second timelines for fault scenarios.

| Label(s) | What it is |
|---|---|
| `ab_baseline`, `ab_final` | **headline matrix**: 14 scenarios, baseline vs. final, interleaved per repetition (final = `v_final`; see `BENCHMARK_RESULTS.md` §0) |
| `ab2_*`, `ab3_*` | later re-runs: Redis outage with retries disabled; high-cardinality + stampede with the cache re-check gated |
| `sat_baseline`, `sat_final3` | saturation sweep 700–1500 rps |
| `g1_*`, `g5_*`, `g7_*` | PostgreSQL frozen for 20 s (original, first fix, guard iterations, final guard) |
| `g2_*`–`g4_*`, `g6_*` | database-guard overhead / spurious-rejection investigation (intermediate iterations + final) |
| `p1_*`–`p4_*` | isolated optimisation A/B runs (settings cache, cached-JSON hit path, ASGI middleware, single-flight) |
| `baseline` | the first, **non-interleaved** matrix — kept as a sanity set only; the machine was ≈ 2× slower then (see `BENCHMARK_RESULTS.md` §0, §9) |
| `experiments/` | `lost_update`, `node_down_startup`, `write_freeze`, `flush_duration`, `claims`, `mutation_smoke` outputs |
| `summary_*.md/csv` | generated tables (`benchmarks/report.py`, `benchmarks/compare.py`) |
| `prof_baseline.raw` | `py-spy --gil` collapsed stacks of the baseline hit path (`benchmarks/profile_summary.py`) |

`raw/*.csv.gz` (`t_rel_s,latency_ms,status,send_lag_ms` for every measured request) is kept **only** for the headline and saturation runs and the final guard runs (`ab_*`, `sat_*`, `g6_*`, `g7_*`); other labels keep their JSON summaries (their `raw_file` fields point to files that were pruned to keep the repository small). Server logs are not committed.
