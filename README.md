# TypeAheadX

## Dataset Architecture

```text
AmazonQAC
  ↓
Normalization + aggregation
  ↓
`data/processed/queries.csv`
  ↓
PostgreSQL `queries` table
```

## Final Dataset Decision

- Raw source dataset: `amazon/AmazonQAC` from Hugging Face
- Raw dataset is not stored in the repository
- Processed application dataset: `data/processed/queries.csv`
- Schema: `query,historical_count`
- The processed CSV is the source of truth for future phases

## Phase 0 Completion

Phase 0 is complete.

The dataset layer is frozen and ready for Phase 1.

## Database Foundation Checks

### Check 6.1 — Schema Exists

`backend/schema.sql` contains:

- primary key
- unique query constraint
- historical count

### Check 6.2 — Prefix Index Exists

Current baseline indexing strategy:

```sql
CREATE INDEX idx_query_prefix
ON queries (query text_pattern_ops);
```

Phase 1 supports prefix search with:

```sql
WHERE query LIKE 'iph%'
```

### Check 6.3 — Ingestion Pipeline Works

`backend/ingest.py` loads `data/processed/queries.csv` into PostgreSQL.

## Validation Tests

All validation queries use the `queries` table in this repository.

### Test 1 — Row Count

```sql
SELECT COUNT(*)
FROM queries;
```

Expected: `>= 100000`

### Test 2 — No Duplicate Queries

```sql
SELECT query, COUNT(*)
FROM queries
GROUP BY query
HAVING COUNT(*) > 1;
```

Expected: `0 rows`

### Test 3 — Null Query Test

```sql
SELECT COUNT(*)
FROM queries
WHERE query IS NULL OR query = '';
```

Expected: `0`

### Test 4 — Top Queries

```sql
SELECT query, historical_count
FROM queries
ORDER BY historical_count DESC
LIMIT 10;
```

Expected: realistic Amazon queries

### Test 5 — Prefix Search Works

```sql
SELECT query, historical_count
FROM queries
WHERE query LIKE 'iph%'
ORDER BY historical_count DESC
LIMIT 10;
```

Expected: iphone-related results

## Repository Layout

- `backend/schema.sql` - database schema
- `backend/ingest.py` - ingestion pipeline
- `backend/query.py` - verification helper
- `data/processed/queries.csv` - production dataset
- `docs/dataset-research.md` - dataset source and acquisition notes
- `docs/dataset-sampling-strategy.md` - preprocessing and sampling strategy
- `docs/dataset-report.md` - final dataset report
- `docs/phase0-dataset-validation.md` - Phase 0 validation checklist
- `docs/reproducibility-report.md` - final Phase 0 completion record
- `docs/adrs/001-storage-engine.md` - storage engine decision
- `docs/adrs/002-dataset-selection.md` - dataset selection decision

## Next Milestone

Phase 1: PostgreSQL-only autocomplete API with latency benchmarking.

No caching or distributed components should be introduced until a baseline is measured.

