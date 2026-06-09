# Backend Storage Notes

This folder contains the PostgreSQL storage helpers used by TypeAheadX.

Repository-wide dataset contract:

- AmazonQAC is the raw source
- `data/processed/queries.csv` is the processed source of truth
- `backend/schema.sql` defines the `queries` table
- `backend/ingest.py` loads the processed CSV into PostgreSQL
- `backend/query.py` is the simple verification helper for Phase 0 storage checks

The repository README documents the dataset pipeline and final Phase 0 conclusion.
