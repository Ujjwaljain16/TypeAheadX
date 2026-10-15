# ADR-005: Trending ranking with read-time decay

**Date:** 2026-10-16
**Status:** Accepted (completes [ADR-003](./003-trending-data-model.md), which chose the `recent_count` / `last_decay_at` columns but left the ranking itself unimplemented)

## Problem
ADR-003 stores a decayed `recent_count` per query, updated when a query is flushed. The documented ranking was `historical_count + 10·recent_count`, but the SQL ordered by `historical_count` only — trending had no effect on what users saw, and the supporting expression index had zero scans. Even if the stored value had been used, it is only decayed *when the query is searched*: a query that went viral yesterday and was never searched again would keep its boost forever.

## Alternatives
1. Keep the stored value and rank by it — wrong for idle queries (see above).
2. Periodic decay job over the whole table — O(rows) work on a schedule, the thing ADR-003 wanted to avoid.
3. **Apply the remaining decay when reading** *(chosen)*:
   `score = historical_count + β·recent_count·exp(−λ·(now − last_decay_at)/3600)`.
4. Precompute top-K per prefix on write — fastest reads, much more machinery; not justified at 150 k rows.

## Decision
Option 3. β = `TRENDING_BETA` (10), λ = `TRENDING_LAMBDA` (0.5 / hour, shared with the write path so both sides decay identically). Ties fall back to `historical_count DESC, query ASC`, so rows that were never searched through `/search` (`recent_count = 0`, i.e. the whole loaded dataset) sort exactly as before. The displayed count stays `historical_count`. The expression index is dropped (`schema.sql`, `migrate.py`): an index cannot express a time-dependent score, and the prefix index narrows the candidate rows before the expression is evaluated.

## Consequences
**Positive:** a query searched ~120 times jumps above far more popular ones and fades by itself (verified end-to-end: 120 searches → flush → rank 1 although its count is 347 < 987; with no new writes it returns to its old rank as `exp(−λΔt)` decays). No cron job.
**Negative:** the score is computed for every row matching the prefix — worst case the 1-character prefix (6 177 rows): 4.4 → 5.2 ms (+0.8 ms, same plan); typical prefixes unchanged (0.27 ms). Results are cached, so a trend becomes visible after the next invalidation (seconds) and an old order can survive ≤ 300 s in the invalidation race.
**Behaviour change:** result order can now differ from raw `historical_count` order when recent searches exist — intended.
**Open:** β and λ are the documented defaults, not tuned against real traffic.
