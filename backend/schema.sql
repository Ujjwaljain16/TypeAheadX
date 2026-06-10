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

CREATE INDEX IF NOT EXISTS idx_trending_score ON queries (
    (historical_count + 10.0 * recent_count) DESC
);
