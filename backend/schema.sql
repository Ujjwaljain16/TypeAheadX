CREATE TABLE IF NOT EXISTS queries (
    id BIGSERIAL PRIMARY KEY,
    query TEXT NOT NULL UNIQUE,
    historical_count BIGINT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_query_prefix
    ON queries (query text_pattern_ops);
