# ADR-006: Write-path durability and database deadlines

**Date:** 2026-10-16
**Status:** Accepted

## Problem
Two coupled questions:
1. **Writes.** Selections arrive in bursts. What durability do we promise, and what happens when the flush fails?
2. **A hung database.** Sync SQLAlchemy/psycopg calls cannot be interrupted client-side. If PostgreSQL stops answering without closing connections (frozen process, black-holed network, stuck failover) the kernel keeps ACKing, so no TCP timeout fires and every cache-missing request holds one of 40 request threads indefinitely; after ≈ 40 of them even cache hits fail. Measured with the database frozen for 20 s: **14 s with zero successful requests, requests hanging ≈ 6 s**.

## Decisions
### Writes: in-memory aggregation, at-most-once, no deadline
* Buffer in process memory (bounded, 50 000 distinct queries; overflow ⇒ explicit `503 + Retry-After`), flush as one atomic statement every 10 s / 100 distinct queries.
* A crash loses ≤ one flush window (≈ 10 s) of counter increments. **Accepted:** the counters are popularity statistics, not financial data; a journal or message broker was not introduced because the measured exposure (≤ 10 s of increments) does not justify the operational cost. Revisit if counters ever feed something that must be exact.
* Failures: unreachable database ⇒ re-queue the uncommitted remainder (bounded); batch rejected while the database is reachable ⇒ bisect and drop only the bad row; committed ⇒ never re-queue.
* **Writes get no deadline.** If a write times out client-side, the statement may still execute when the database resumes; retrying or re-queueing it would double count. Blocking (at-most-once) is the safe behaviour; the bounded buffer protects memory meanwhile. A deadline for writes would need an idempotency key (e.g. a batch id stored in the same transaction).

### Reads: deadline + bulkhead + circuit breaker (`database/guard.py`)
* Read-path database calls run on ≤ 15 daemon worker threads (= SQLAlchemy pool size); the request thread waits at most 2 s.
* A caller that cannot get a slot within 50 ms is rejected (`503`), never queued behind hung calls. A rejection is *load*, not a sick database, so it does not open the breaker (it only releases a half-open probe grant).
* The first timeout or connection-level error opens a breaker for 5 s: misses then fail instantly (`503 + Retry-After`) while cache hits are untouched; one probe tests recovery. The breaker class is shared with the Redis nodes ([ADR-004](./004-cache-failure-handling.md)).

## Alternatives considered
* `statement_timeout` / TCP keepalives / `tcp_user_timeout` — server-side or kernel-side; none help when the server process is frozen but the kernel still ACKs.
* Async driver with task cancellation — the "right" long-term answer (abandoning the socket needs no server cooperation) but a rewrite of repository, service, endpoints and flush.
* Retrying writes with a deadline — double-counting risk (above).

## Consequences
**Measured (20 s freeze, 2 runs):** seconds with zero successes 14 → **0**; slowest request ≈ 6 s → **2.0 s** (the deadline); p99 ≈ 5 s → **12–18 ms**; error *rate* unchanged (≈ 26–32 %: misses cannot be answered) but errors are immediate and cached prefixes keep being served.
**Cost when healthy:** ≈ +0.4 ms median on the miss path (one thread hop), p99 not worse, no spurious rejections in 4 runs at 400 rps of all-miss traffic. An earlier setting (12 slots, instant rejection, saturation opened the breaker) produced occasional 503s under short stalls — found by this measurement and fixed.
**Residual:** up to 15 worker threads can stay blocked inside hung calls until the database answers or the OS drops the connection (daemon threads — they never block process exit); the guard does not tear down the hung connection. The 2 s default should be tuned to the real query-time distribution.
