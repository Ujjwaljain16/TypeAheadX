# Source this file: benchmark environment pointing at the disposable taxbench stack.
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://postgres:postgres@localhost:47433/typeaheadx}"
export PG_DSN="${PG_DSN:-postgresql://postgres:postgres@localhost:47433/typeaheadx}"
export REDIS_NODES="localhost:47379,localhost:47380,localhost:47381"
export REDIS_URL="redis://localhost:47379"
export CACHE_PROVIDER="${CACHE_PROVIDER:-distributed}"
export VIRTUAL_NODES=500
# Integration tests (backend/tests): a separate database, created on demand. Redis nodes are FLUSHED by tests.
export TAX_TEST_PG_DSN="postgresql://postgres:postgres@localhost:47433/typeaheadx_test"
export TAX_TEST_REDIS_NODES="localhost:47379,localhost:47380,localhost:47381"
