# Lessons learned

Each lesson is something the original design got wrong or assumed, how it was found, and the general principle. Evidence: [`audit/FINDINGS.md`](../audit/FINDINGS.md).

1. **A feature isn't done until you've broken it.** Active cache invalidation, node-failure tolerance, horizontally safe writes and trending ranking all *looked* implemented and had been described as working. Invalidation deleted `suggest:<p>` while reads used `suggestion:<p>` (never matched); a dead cache node caused a total outage; concurrent flushers lost 67–70 % of updates; the ranking ignored the trending score. Each was exposed only by an experiment that provoked it (write → flush → read; kill a node; run N flushers; query the ordering). → *Test the failure, not the happy path; derive keys from one function.*

2. **Graceful degradation can be the failure.** "On a Redis error, treat it as a miss" is right per request but wrong in aggregate: with blocking I/O in a bounded thread pool, each request to the dead node held a thread for seconds and starved everything else. → *Degrade by not calling the dependency (circuit breaker), and bound every wait.*

3. **Library defaults are part of your design.** redis-py ≥ 6 retries failures 3× with exponential backoff: a configured 250 ms timeout cost 5–8 s. My first fix for the outage kept the default and still stalled for 5 s at the moment of failure; it was visible only in the per-second timeline. → *Read the effective retry/timeout policy of every client; test the transition, not just the steady state.*

4. **Read-modify-write across processes loses updates.** `SELECT` → add in Python → `UPSERT` was fine with one worker and silently wrong with several. → *Push the merge into the database (`SET x = x + δ` under the row lock); order rows consistently to avoid deadlocks.*

5. **At-most-once vs. at-least-once is a decision, not an accident.** A timed-out write may still run later; retrying it double-counts. So reads got deadlines and breakers while writes deliberately block (bounded buffer) — and the trade-off is written down ([ADR-006](./adrs/006-write-path-durability-and-db-deadlines.md)). → *Give a deadline only to operations that are safe to abandon.*

6. **Bound everything that user input can grow.** An unauthenticated endpoint accepted a 50 MB body (+147 MB RSS), unlimited distinct strings, and one unindexable string could erase a whole batch. → *Validate once, in one place, for both read and write paths; cap sizes and cardinalities; make backpressure explicit (503 + `Retry-After`) and counted.*

7. **Stored time-decayed values must be decayed at read time.** `recent_count` was decayed only when written, so an idle viral query would stay "trending" forever, and the index on the stored expression could never rank correctly. → *Store the value and its timestamp; evaluate the decay where you read.*

8. **Measure like a skeptic.** Closed-loop chunks of 100 are not "100 000 concurrent requests"; 10 000 synthetic keys cap the cache miss count whatever the cache does; a machine's speed drifts 2× over hours, so only interleaved comparisons count; my own tooling had artifacts (15 ms timer granularity, a `psutil` call holding the GIL, a stat counter that lagged a second) that I found by calibrating the harness against `/health`. And I once "found" 99 % data loss that was a drain check reading the wrong signal — the corrected experiment showed no loss. → *Calibrate the instrument, replicate, interleave, and distrust a result that tells you what you expected.*

9. **Hot keys are a workload property.** A Zipf stream put ≈ 60 % of requests on one Redis node although the ring gave it 34 % of the keys. Consistent hashing balances keys, not traffic. → *Say what a mechanism balances; add L1 caching or replication only when a measurement shows the node is the bottleneck.*

10. **Documentation rots into claims.** Docs asserted behaviours (vnodes "instantly deleted" from the ring, 100 % availability, sub-millisecond latency) that the code never had. The fix was to tie every statement in the docs to a test, a benchmark or a ✔/✘ in the audit.
