# ADR-002: Dataset Selection

**Date:** 2026-06-10
**Status:** Accepted

## Problem

TypeAheadX needs a dataset that supports realistic autocomplete behavior, prefix-heavy query shapes, and enough scale to validate a storage layer with 100,000+ queries before Phase 1 begins.

## Alternatives

1. Amazon Product Titles
2. Wikipedia Titles
3. AOL Query Logs
4. AmazonQAC

## Decision

Choose AmazonQAC.

## Consequences

**Positive:** AmazonQAC is purpose-built for query autocomplete and is based on real Amazon search logs, which makes it a much better fit for an autocomplete assignment than generic product-title or title corpora. It also provides realistic prefixes, session context, and popularity metadata that match the behavior TypeAheadX is meant to model. The repository can therefore treat `data/processed/queries.csv` as a deterministic, documented output of the AmazonQAC preprocessing contract.

**Negative:** The raw dataset is very large, so preprocessing must be streaming-oriented and sampled carefully.

**Neutral:** The project must document its sampling strategy and keep the processed slice small enough for PostgreSQL ingestion while still preserving realistic distribution characteristics.
