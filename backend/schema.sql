CREATE TABLE IF NOT EXISTS queries (
    id BIGSERIAL PRIMARY KEY,
    query TEXT NOT NULL UNIQUE,
    historical_count BIGINT NOT NULL DEFAULT 0,
    recent_count FLOAT NOT NULL DEFAULT 0.0,
    last_decay_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_searched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_query_prefix
    ON queries (query text_pattern_ops);

-- NOTE: the former idx_trending_score expression index was removed: the ranking decays recent_count at read
-- time, which an index cannot express, and the index had zero scans while costing a write per upsert.
-- Existing databases: DROP INDEX IF EXISTS idx_trending_score;  (migrate.py does this)
