# ADR-001: Storage Engine Decision

**Date:** 2026-06-10
**Status:** Accepted

## Problem

TypeAheadX needs a storage layer that can hold a normalized query corpus, support exact lookups, and prepare the system for prefix autocomplete without introducing caching or distributed components too early.

## Alternatives

1. PostgreSQL only
2. PostgreSQL plus trigram-based fuzzy search as the primary strategy
3. A search engine such as Elasticsearch
4. A non-relational store

## Decision

Use PostgreSQL as the storage engine for Phase 0, with the `queries` table as the source of truth and a prefix index using `text_pattern_ops` to support `WHERE query LIKE 'iph%'` style lookups in Phase 1.

## Consequences

**Positive:** The storage layer stays simple, deterministic, and easy to validate before any application logic is introduced.

**Negative:** This phase does not provide fuzzy search or distributed retrieval.

**Neutral:** Future optimizations can be evaluated later, but they must not replace the prefix-optimized PostgreSQL baseline until a benchmark justifies it.
