# TypeAheadX backend

FastAPI service: prefix suggestions from a consistent-hash Redis cache in front of PostgreSQL, popularity updates through a bounded write buffer, trending ranking with read-time decay. Design: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).

## Layout
```
app/
  main.py                 app + lifespan (warm-up, final flush), middleware (timing, body limit, CORS), /health /ready /metrics
  api/                    suggestions.py (GET /suggest) · search.py (POST /search, /write/metrics) · cache.py (/cache/debug, /cache/metrics)
  services/               suggestion_service.py (cache-aside + single-flight) · normalization.py (the one normaliser) · trending_calculator.py (reference decay formula, used by tests)
  cache/                  distributed_cache.py · redis_node.py (client + breaker) · consistent_hash_ring.py · redis_cache.py (1-node ring) · memory_cache.py · metrics.py
  database/               config.py (settings) · session.py (engine, timeouts) · guard.py (deadline/bulkhead/breaker for reads)
  repositories/           query_repository.py (prefix+ranking query, atomic upsert)
  write_buffer/           buffer.py · batch_worker.py · metrics.py
  utils/                  breaker.py (shared circuit breaker)
schema.sql · ingest.py · migrate.py · requirements*.txt (lock file pinned and audited)
tests/                    unit + integration (real PostgreSQL/Redis, opt-in) + property-based
```

## Run
```bash
docker compose up -d                                  # from the repo root
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt     # .venv/bin/pip on Linux/macOS
cp .env.example .env
python ingest.py                                      # creates the schema, loads data/processed/queries.csv (150 000 rows)
uvicorn app.main:app --port 8000
```
`python migrate.py` upgrades an older database (adds columns, drops the unused `idx_trending_score`).

## Configuration (environment / `.env`)
| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5433/typeaheadx` | |
| `CACHE_PROVIDER` | `memory` (`.env.example`: `distributed`) | `distributed` (ring), `redis` (one node), `memory` (per process — **no** size bound) |
| `REDIS_NODES`, `VIRTUAL_NODES` | `localhost:6379,6380,6381`, `500` | must be identical on every instance |
| `CACHE_TTL_SECONDS` | 300 | |
| `REDIS_TIMEOUT_SECONDS`, `REDIS_BREAKER_SECONDS` | 0.25, 5 | per-node timeout / breaker window |
| `DB_QUERY_TIMEOUT_SECONDS`, `DB_MAX_CONCURRENCY`, `DB_BREAKER_SECONDS` | 2, 15, 5 | read-path database deadline / bulkhead / breaker |
| `DB_POOL_TIMEOUT_SECONDS`, `DB_CONNECT_TIMEOUT_SECONDS` | 5, 5 | |
| `MAX_PREFIX_LENGTH`, `MAX_QUERY_LENGTH`, `MAX_REQUEST_BYTES` | 64, 200, 16384 | input limits |
| `WRITE_BUFFER_SIZE`, `WRITE_BUFFER_FLUSH_INTERVAL`, `WRITE_BUFFER_MAX_UNIQUE` | 100, 10, 50000 | flush policy (distinct queries / seconds) and buffer cap |
| `TRENDING_BETA`, `TRENDING_LAMBDA` | 10, 0.5 | ranking weight and decay per hour |
| `CORS_ORIGINS`, `ENABLE_DEBUG_ENDPOINTS` | `*`, `true` | set debug endpoints to `false` outside development |

## Tests
```bash
pip install -r requirements-dev.txt
pytest                                  # 71 tests need no services; 65 integration tests are skipped with a reason
source ../benchmarks/env.sh && docker compose -p taxaudit -f ../benchmarks/docker-compose.bench.yml up -d
pytest --cov=app                        # all 136 against real PostgreSQL + Redis (database typeaheadx_test, Redis is FLUSHED)
```
The integration tests refuse to run unless `TAX_TEST_PG_DSN` points to a local database whose name ends in `_test`.
