# Data Directories

- `data/processed/` contains `queries.csv`, the normalized dataset used by the ingestion pipeline.

## Loading Instructions

To ingest the dataset into the PostgreSQL database, ensure your database is running and the schema is migrated, then run the ingestion script from the `backend/` directory:

```bash
cd ../backend
# Make sure your virtual environment is activated
python ingest.py
```
This will read the 150,000 queries from `data/processed/queries.csv` and execute high-performance batch UPSERTS to safely populate the `queries` table.

---

# Quality Report

## Summary Statistics
- **Total Processed Rows**: 2000000
- **Unique Queries**: 1244769
- **Average Query Length**: 21.83 characters
- **Median Query Length**: 21.0 characters
- **95th Percentile Length**: 37.0 characters

## Top 10 Queries
- iphone 15 pro case: 987
- iphone 14 pro max case: 908
- halloween decorations: 903


## Final Dataset Contract

- Raw source: AmazonQAC from Hugging Face (`amazon/AmazonQAC`)
- Processing input: approximately 2,000,000 streamed interactions from the train split
- Processing output: `data/processed/queries.csv`
- Schema: `query,historical_count`
- Retained slice: top 150,000 queries by historical popularity

## Final Statistics

- Processed rows: 150,000
- Unique queries: 150,000
- Observed interactions streamed: 2,000,000

## Prefix Distribution

Tracked prefixes:

- iph
- sam
- jav
- pyt
- mac
- lap
- usb

Top 20 prefixes are recorded in the reproducibility report and should be regenerated from the processed CSV before Phase 1.

## Validation Summary

- Queries are normalized to lowercase.
- Leading and trailing whitespace is removed.
- Repeated internal whitespace is collapsed.
- Empty or malformed queries are excluded.
- Duplicate final queries are aggregated by actual occurrence counts.
- PostgreSQL ingests the processed CSV directly.
