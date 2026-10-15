\echo === OLD ranking, prefix a
EXPLAIN (ANALYZE, BUFFERS) SELECT query, historical_count FROM queries WHERE query LIKE 'a%' ESCAPE '\' ORDER BY historical_count DESC, query ASC LIMIT 10;
\echo === NEW ranking, prefix a
EXPLAIN (ANALYZE, BUFFERS) SELECT query, historical_count FROM queries WHERE query LIKE 'a%' ESCAPE '\' ORDER BY (historical_count + 10.0::double precision * recent_count * exp(-0.5::double precision * GREATEST(EXTRACT(EPOCH FROM (NOW() - last_decay_at)), 0) / 3600.0)) DESC, historical_count DESC, query ASC LIMIT 10;
\echo === NEW ranking, prefix iphone 15
EXPLAIN (ANALYZE, BUFFERS) SELECT query, historical_count FROM queries WHERE query LIKE 'iphone 15%' ESCAPE '\' ORDER BY (historical_count + 10.0::double precision * recent_count * exp(-0.5::double precision * GREATEST(EXTRACT(EPOCH FROM (NOW() - last_decay_at)), 0) / 3600.0)) DESC, historical_count DESC, query ASC LIMIT 10;
