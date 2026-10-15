\set ON_ERROR_STOP off
ANALYZE queries;
\echo === A. literal prefix 'a' (6177 matches) -- what a custom plan sees
EXPLAIN (ANALYZE, BUFFERS) SELECT query, historical_count FROM queries WHERE query LIKE 'a' || '%' ORDER BY historical_count DESC, query ASC LIMIT 10;
\echo === B. literal prefix 'iphone 15'
EXPLAIN (ANALYZE, BUFFERS) SELECT query, historical_count FROM queries WHERE query LIKE 'iphone 15' || '%' ORDER BY historical_count DESC, query ASC LIMIT 10;
\echo === C. no-match prefix
EXPLAIN (ANALYZE, BUFFERS) SELECT query, historical_count FROM queries WHERE query LIKE 'zzzzzz' || '%' ORDER BY historical_count DESC, query ASC LIMIT 10;
\echo === D. forced GENERIC plan (parameter $1, as a prepared stmt can fall into after 5 execs)
SET plan_cache_mode = force_generic_plan;
PREPARE g(text, int) AS SELECT query, historical_count FROM queries WHERE query LIKE $1 || '%' ORDER BY historical_count DESC, query ASC LIMIT $2;
EXPLAIN (ANALYZE, BUFFERS) EXECUTE g('iphone 15', 10);
RESET plan_cache_mode;
\echo === E. index sizes
SELECT relname, pg_size_pretty(pg_relation_size(oid)) FROM pg_class WHERE relname IN ('queries','idx_query_prefix','idx_trending_score','queries_query_key','queries_pkey');
\echo === F. index usage stats
SELECT indexrelname, idx_scan, idx_tup_read FROM pg_stat_user_indexes WHERE relname='queries';
