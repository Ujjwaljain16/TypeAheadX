# Phase 0 Dataset Validation

## Exit Criteria

1. Total rows >= 100,000
2. Queries are unique
3. No empty queries
4. Prefix-search examples exist

## Validation Queries

```sql
SELECT COUNT(*) AS total_rows FROM queries;
SELECT COUNT(*) AS unique_rows FROM (SELECT DISTINCT query FROM queries) t;
SELECT COUNT(*) AS empty_rows FROM queries WHERE query = '';
SELECT COUNT(*) AS duplicate_rows FROM (
	SELECT query
	FROM queries
	GROUP BY query
	HAVING COUNT(*) > 1
) t;
```

## Prefix Search Examples

Run these checks after the processed dataset is ingested into PostgreSQL:

```sql
SELECT query, historical_count FROM queries WHERE query LIKE 'iphone%';
SELECT query, historical_count FROM queries WHERE query LIKE 'samsung%';
SELECT query, historical_count FROM queries WHERE query LIKE 'laptop%';
SELECT query, historical_count FROM queries WHERE query LIKE 'usb%';
SELECT query, historical_count FROM queries WHERE query LIKE 'air%';
SELECT query, historical_count FROM queries WHERE query LIKE 'wire%';
SELECT query, historical_count FROM queries WHERE query LIKE 'head%';
```

## Expected Outcome

- The storage layer should contain at least 100,000 normalized queries.
- Duplicate final queries should be collapsed before ingestion.
- Empty rows should be absent.
- Prefix lookups should return real rows for the example e-commerce prefixes once the processed dataset is loaded.

## Completion Statement

Phase 0 is complete. The next engineering milestone is Phase 1: PostgreSQL-only autocomplete API with latency benchmarking.

## Database Foundation

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
