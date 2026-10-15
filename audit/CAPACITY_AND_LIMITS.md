# Capacity and limits

Scope: what was **measured** on one machine with one API worker, what is **inferred**, and what is **unknown**.
No linear extrapolation to production scale is made or implied.

## Tested operating envelope
| Dimension | Tested | Not tested |
|---|---|---|
| API processes | 1 uvicorn worker (Windows asyncio loop) | `--workers N`, multiple hosts, Linux/uvloop |
| Offered load | up to 1 500 rps (hit path), 400 rps (DB-only), 300 rps (read/write) | > 850 rps is generator-limited (dispatch lag) |
| Dataset | 150 000 rows (15 MB table) | millions of rows; index/cache behaviour at that size |
| Duration | 20–25 s windows (3 reps), one 120 s sustained run per variant | hours/days (soak), memory fragmentation, TTL churn |
| Redis | 3 containers, 1 CPU each, `noeviction`, no `maxmemory` | eviction, persistence, replication, real network RTT |
| PostgreSQL | 15, default config, 2 CPU / 2 GB, tmpfs | replicas, vacuum/bloat after many updates, disk-bound IO |
| Faults | stop / freeze of one Redis node; freeze of PostgreSQL | network partitions, slow (not dead) dependencies, disk full |

## Measured capacity (single worker, this machine)
| Workload | Baseline | Final | Limiting resource (observed) |
|---|---|---|---|
| Cache-hit path (`warm`) | clean to ≈ 600 rps (p99 65 ms at 600, CPU 87 %); collapses at ≥ 700 rps (goodput ≈ 280/s, 60–98 % errors) | clean at 700 rps (p99 6.8–229 ms by run), goodput ≈ 800 at 850; degrades gradually above | API process CPU (≈ 100 % of one core at the knee) — specifically the single event-loop thread + GIL |
| CPU per hit-path request | ≈ 1.46 ms (74 % @ 500 rps) | ≈ 0.7–0.8 ms (36 % @ 500 rps) | |
| Popular-prefix workload | 300 rps clean, collapse at 400 | 400 rps clean (p50 1.3 ms) | same |
| Read/write 95/5 | collapse at 300 rps (30 % errors) | 300 rps clean (p99 10 ms) | same |
| Database-only path | 400 rps with p99 18 ms, CPU 86 % (client side) | 400 rps, p99 8.3 ms, CPU 53 % | **not saturated** — PostgreSQL capacity is unmeasured; cache offers little latency benefit at this dataset size (miss path p50 ≈ 4–6 ms vs hit 1.1–2 ms) |
| Burst 5× for 5 s (100 → 500 rps) | p50 710 ms, 1.5 % errors | p50 2.2 ms, 0 errors | final handles a short burst within the 700 rps knee |

Capacity statement that the evidence supports: *on this hardware, one API worker serves ≈ 650 (baseline) vs ≈ 750–800 (final) cache-hit
requests per second before queueing collapses; per-request CPU is ≈ halved.* How this scales with workers or in production is **undetermined**.
Price/performance was not evaluated (no cloud resources were used).

## First bottleneck, by regime
1. **Hit path:** API-process CPU (Python request handling). Redis (3 nodes, ≈ 0.3 ms per GET) and PostgreSQL were far from saturated.
2. **Miss path:** per-request latency ≈ 4–6 ms is dominated by Redis GET + PostgreSQL round trip + Docker-proxy latency, not by query execution
   (index scan 0.04–3.6 ms). Throughput is again limited by API CPU.
3. **Failure regimes:** thread-pool starvation (baseline, Redis node down) and unbounded waiting on a frozen database (both versions).

## Memory
* API process ≈ 82–93 MB RSS; write buffer ≈ 30 MB per 150 000 distinct queries (baseline unbounded; final capped at 50 000 distinct = ≈ 10 MB).
* Redis ≈ 540–700 B per cached prefix. The documented keyspace (every prefix of every query, up to 64 characters) was **not** measured at full scale;
  `noeviction` + no `maxmemory` means a full cache would be bounded only by TTL (300 s) × arrival of distinct prefixes. A production deployment must set
  `maxmemory` + `allkeys-lru` (untested here).

## Durability / consistency limits (design, not benchmark)
* Buffered `POST /search` events live only in API-process memory: a crash/kill loses up to ≈ 10–11 s of events (flush interval 10 s on a 1 s tick, or 100 distinct queries).
  Graceful shutdown flushes. A durable log was **not** added: no evidence that the exposure (popularity counters) justifies a broker; the quantified exposure is
  "≤ one flush window of counter increments".
* Read-your-writes is not provided (≤ 10 s buffering + invalidation); stale entries can survive up to the 300 s TTL in a race (F-31).
* Per-process state: write buffer, single-flight table and metrics are per worker. With N workers, ranking updates are safe (atomic SQL) but coalescing is per process.

## What would have to be measured before claiming production readiness
Multi-worker scaling and the load generator on a separate host; Linux; ≥ 1 M-row dataset (index size, planner behaviour, `ORDER BY` top-N cost for 1-char prefixes);
Redis eviction and memory at full keyspace; PostgreSQL under sustained write + read mix with vacuum; real network RTT and TLS; soak ≥ 24 h; slow-dependency (latency, not death) injection;
a client-side deadline strategy for a hung database (F-27); authentication and rate limiting.
