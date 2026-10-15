# Engineering audit

An independent, evidence-driven audit of TypeAheadX: defects were reproduced at runtime, fixed with regression tests, and every performance claim was measured with an open-loop generator and interleaved baseline-vs-candidate runs. Baseline = commit `a45f129`.

| Read this | For |
|---|---|
| [`FINAL_REPORT.md`](./FINAL_REPORT.md) | the whole story: assessment, critical findings, security, results, claims review, residual risks, verification checklist |
| [`FINDINGS.md`](./FINDINGS.md) | 31 findings with severity, evidence, reproduction, fix, regression test and status |
| [`BENCHMARK_RESULTS.md`](./BENCHMARK_RESULTS.md) | every benchmark: commands, environment, sample counts, percentiles, CIs, limitations |
| [`OPTIMIZATIONS.md`](./OPTIMIZATIONS.md) | each optimisation: problem → hypothesis → isolated A/B → decision, plus what was rejected |
| [`CAPACITY_AND_LIMITS.md`](./CAPACITY_AND_LIMITS.md) | measured envelope, first bottleneck per regime, what is *not* known |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | the architecture as reverse-engineered from the code at the baseline (the current design is in [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)) |
| [`REPRODUCING.md`](./REPRODUCING.md) | clean-checkout instructions for tests, benchmarks, experiments, profiling |
| [`results/`](./results/README.md) | machine-readable measurements (JSON/CSV), raw per-request data for the headline runs, profile, experiment logs |

Status after the follow-up work: the trending-ranking finding (F-10) and the frozen-database finding (F-27, reads) are **fixed** — see the notes at the top of `FINDINGS.md`; the baseline-oriented text in `ARCHITECTURE.md` and parts of `FINAL_REPORT.md` is intentionally left as the historical record of what was found.
