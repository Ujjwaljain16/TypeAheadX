# ADR-003: Trending Data Model

**Date:** 2026-06-10
**Status:** Accepted

## Problem
Trending requires a recency signal to score fresh queries higher than older ones. We need to decide how to persist this recency data. The choice affects implementation complexity, query performance, and the amount of data we need to store. Two designs are possible: a separate `search_events` table storing raw events, or additional fields (`recent_count`, `last_decay_at`) on the `queries` table.

## Alternatives Considered
- **Design A:** `queries` + `search_events` (two tables). The trending engine periodically scans raw events to compute scores.
- **Design B:** `queries` with decay fields (`historical_count`, `recent_count`, `last_decay_at`). The trending engine reads pre-computed scores.

## Decision
**Design B — single `queries` table with `historical_count`, `recent_count`, and `last_decay_at`.** The exponential decay formula will be applied dynamically during each batch flush: `new_recent = old_recent * exp(-lambda * hours_elapsed) + delta`.

## Consequences
**Positive:** No expensive table scans required for the `/trending` endpoint. The write path is simple and consolidated into a single UPSERT. It is mathematically elegant and easy to explain.
**Negative:** Raw search events are not stored permanently. We cannot retroactively recompute trending with a different lambda value since the raw event log is discarded.
**Neutral:** The decay logic must be carefully synchronized during the batch flush. We have decoupled this logic into a dedicated `TrendingCalculator` service.
