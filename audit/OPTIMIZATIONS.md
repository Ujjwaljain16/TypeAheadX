# Optimization changelog

Method: profile → hypothesis → one isolated change → **interleaved** A/B against the previous variant
(`benchmarks/run_ab.sh`, 3 repetitions, 20 s measured window + 5 s warm-up each, single uvicorn worker, same seed)
→ keep/revert. "Variant" directories are snapshots of the working tree after each step; the numbers below come from
`audit/results/{p1,p2,p3,p4}_*` and `audit/results/experiments/flush_duration.jsonl`
(summary: `audit/results/summary_optimizations.md`). Latencies are end-to-end HTTP from an open-loop generator on the
same machine; CPU is the API process (% of one core). Repetition spread is shown as min–max.

Reference point: the **correctness/reliability fixes alone (variant `v_fix`) did not change hot-path performance**:
warm p50 1.92 ms (1.87–1.99) vs baseline 1.89 ms (1.88–1.91) at 250 rps, CPU 38.4 % vs 37.4 %.

## Profile that drove the work (baseline, 200 rps of cache hits, `py-spy --gil`, 907 samples)
| Share of GIL time | Where |
|---:|---|
| 21.5 % | `get_settings()` → `pydantic_settings.__init__` (12.7 %) + env/`.env` parsing, per request |
| ≈ 25 % | `starlette.middleware.base` (the `@app.middleware("http")` wrapper) and everything under it |
| 10.5 % | Redis `GET` (socket read) |
| ≈ 13 % | handler incl. pydantic model construction/validation |

(`audit/results/prof_baseline.raw`; reproduce with `benchmarks/profile_summary.py`. Sampling error with 907 samples is several points; use the ordering, not the decimals.)

---

## O-1 Cache the settings object  (kept)
| Field | |
|---|---|
| Problem | `Depends(get_settings)` built `Settings()` per request (F-15): 21.5 % of hit-path CPU |
| Hypothesis | `lru_cache` removes ≈ 20 % of CPU and ≈ 0.3–0.4 ms of latency |
| Change | `database/config.py`: `@lru_cache(maxsize=1)` on `get_settings` |
| Correctness | settings are read once per process; env changes need a restart (or `get_settings.cache_clear()`); 119 tests |
| Result (warm, 3 interleaved reps) | 200 rps: p50 1.99 → **1.55 ms**, p99 2.9 → 2.4 ms, CPU 23.5 → 20.6 %. 250 rps: p50 1.92 → **1.50 ms** (−22 %), p99 2.9 → 2.4, CPU 38.4 → **28.0 %** (−27 %) |
| Trade-off | none material |
| Decision | **Keep** |

## O-2 Serve cached JSON directly on a hit  (kept)
| Field | |
|---|---|
| Problem | Hit path did `json.loads` → build `SuggestionItem`s → `SuggestionResponse` → FastAPI re-validates and re-serialises |
| Hypothesis | Storing the complete response body in Redis and returning it as a `Response` removes ≈ 10 % CPU |
| Change | `SuggestionService.suggest_json`, `CacheInterface.get_raw/set_raw`, `/suggest` returns `Response(content=…)` (OpenAPI schema unchanged via `response_model`); malformed/old-format entries are misses |
| Correctness | response bytes are the model's own `model_dump_json()` (same field order/compact JSON); tests for malformed entries, key format, determinism |
| Result (vs O-1) | 250 rps: p50 1.76 → **1.62 ms** (min–max 1.75–1.81 → 1.29–1.67), CPU 31.0 → **27.2 %** (−12 %). 350 rps: p50 1.64 → 1.53, CPU 42.7 → **35.7 %** (−16 %). p99 improved at both rates but with overlapping ranges |
| Trade-off | cached value format changed (rolling deploys degrade to misses, never errors); a corrupt-but-well-prefixed entry would be served verbatim (Redis is a trusted store) |
| Decision | **Keep** (CPU effect consistent in 3/3 repetitions; latency effect small) |

## O-3 Plain-ASGI timing middleware  (kept, modest)
| Field | |
|---|---|
| Problem | `BaseHTTPMiddleware` adds a task + memory stream per request |
| Change | `TimingMiddleware` (pure ASGI) in `main.py`; same header, added last (outermost) |
| Result (vs O-2) | 250 rps: CPU 27.5 → **23.5 %** (−15 %), 350 rps: 35.2 → 32.6 % (−7 %); p50 1.55 → 1.55 / 1.46 → 1.39 ms; **p99 not distinguishable** (3.0 vs 3.8 ms, ranges overlap) |
| Decision | **Keep** — real but small CPU gain, no latency claim |

## O-4 Single-flight for concurrent identical misses  (kept)
| Field | |
|---|---|
| Problem | 200 simultaneous misses for one prefix executed 3.5–10 database queries (F-25) |
| Change | `_single_flight` in `SuggestionService` (leader loads and stores; followers wait ≤ 5 s on an event, then fall back to their own query); double-check of the cache after becoming leader; the service is now a process-wide singleton so the table is shared |
| Result (stampede: 200 concurrent × 20 prefixes, 5 interleaved reps, exact statements from the PostgreSQL log) | baseline **3.5–10.1** queries/prefix (session-dependent) → **1.0 in all 15 runs**; burst p50 ≈ 430 → ≈ 180 ms (headline matrix; 241 → ≈ 85 ms in the isolated early session) (the p50 gain includes O-1…O-3: variant before O-4 had p50 ≈ 110 ms, 6.0–8.7 queries/prefix) |
| Trade-off | scope is one process: with N workers up to N queries per prefix remain possible; followers occupy a thread while waiting (no worse than querying) |
| Tests | `test_service.py`: 40 racing threads → 1 query; different keys not serialised; leader failure only fails the leader |
| Decision | **Keep** |

## O-5 Batched cache invalidation  (kept; measured platform quirk)
| Field | |
|---|---|
| Problem | one `DEL` round trip per prefix (≈ 1 600 for 100 queries) |
| Change | `delete_many`: group keys by node, `DEL k1…k100` per command; skips nodes whose breaker is open |
| Measurement | 600 keys on one node: chunks of 10 → 12.0 ms, 25 → 5.6, 50 → 2.7, **100 → 2.1**, 200 → 1.6, **500 → 96 ms** (a single 12 kB command stalls ≈ 90 ms on this Docker-Desktop/Windows path — probably a TCP ack interaction; not verified on Linux). Chosen: 100 |
| Result (flush of 100 distinct queries, includes DB write; 3 interleaved × 30 rounds) | baseline 493–561 ms median → O-5 alone (500-chunks) 245 ms → with 100-chunks **14 ms** (in combination with O-6) |
| Decision | **Keep**, chunk size 100 |

## O-6 One-statement upsert  (kept)
| Field | |
|---|---|
| Problem | `executemany` of 100 single-row upserts (+ a preceding SELECT in the baseline) |
| Change | `INSERT … SELECT … FROM unnest(:queries, :deltas) ORDER BY q ON CONFLICT DO UPDATE …` — one round trip, deterministic lock order, decay computed in SQL |
| Result | flush 245 → **152 ms** (with 500-key DEL chunks), then → **14 ms** with O-5's 100-key chunks. Isolated DB write for 100 rows: 5.7 ms |
| Correctness | equivalent to the reference calculator (`test_sql_decay_matches_reference_calculator`); atomic under concurrency (F-06) |
| Decision | **Keep** |

---

## Evaluated and not done
| Idea | Why not |
|---|---|
| Larger SQLAlchemy pool / prepared-statement tuning | DB path is not the bottleneck at the tested rates (see BENCHMARK_RESULTS `pgonly`); the generic-plan hypothesis was tested (60 repeated executions through the real client path stayed at ≈ 2 ms; forced generic plan is 11 ms vs 0.36 ms) and **not reproduced** |
| Dropping `idx_trending_score` | would change schema; evidence in F-10 — decision belongs with the ranking decision |
| L1 in-process LRU / hot-key replication | the "hot shard" explanation in the docs was not validated (see FINAL_REPORT §Claims); no measured need |
| `orjson`, `uvloop` | no new dependency without a profile that shows JSON/event-loop as dominant after O-1…O-3 (uvloop is unavailable on Windows anyway) |
| Async Redis client | would remove a thread hop; large change, no measured need at the tested load |
| Per-process → shared single-flight (Redis lock) | complexity; per-process already removes the observed amplification |
