from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    database_url: str = Field("postgresql+psycopg://postgres:postgres@localhost:5433/typeaheadx", validation_alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379", validation_alias="REDIS_URL")
    cache_ttl_seconds: int = Field(default=300, validation_alias="CACHE_TTL_SECONDS")
    cache_provider: str = Field(default="memory", validation_alias="CACHE_PROVIDER")
    redis_nodes: str = Field(default="localhost:6379,localhost:6380,localhost:6381", validation_alias="REDIS_NODES")
    virtual_nodes: int = Field(default=500, validation_alias="VIRTUAL_NODES")
    # Per-operation Redis timeout. A cache miss costs ~2 ms (PostgreSQL), so waiting longer than this
    # for Redis is never worth it; the previous 1 s let a dead node starve the whole thread pool.
    redis_timeout_seconds: float = Field(default=0.25, validation_alias="REDIS_TIMEOUT_SECONDS")
    # After a failure a node is skipped (treated as a miss) for this long before a single probe retries it.
    redis_breaker_seconds: float = Field(default=5.0, validation_alias="REDIS_BREAKER_SECONDS")
    max_prefix_length: int = Field(64, validation_alias="MAX_PREFIX_LENGTH")
    default_limit: int = Field(10, validation_alias="SUGGESTION_LIMIT")
    # Maximum length of a recorded search (POST /search). Must stay well under the btree
    # index-row limit (~2.7 kB) even for 4-byte code points.
    max_query_length: int = Field(200, validation_alias="MAX_QUERY_LENGTH")
    # Request bodies larger than this are rejected with 413 before being buffered (valid bodies are < 1 kB).
    max_request_bytes: int = Field(default=16_384, validation_alias="MAX_REQUEST_BYTES")
    # Fail fast instead of piling requests up behind a sick database (SQLAlchemy default pool wait: 30 s).
    db_pool_timeout_seconds: float = Field(default=5.0, validation_alias="DB_POOL_TIMEOUT_SECONDS")
    db_connect_timeout_seconds: int = Field(default=5, validation_alias="DB_CONNECT_TIMEOUT_SECONDS")
    # Read-path database deadline / bulkhead / breaker (app/database/guard.py). Queries normally take ~5 ms.
    db_query_timeout_seconds: float = Field(default=2.0, validation_alias="DB_QUERY_TIMEOUT_SECONDS")
    db_max_concurrency: int = Field(default=15, validation_alias="DB_MAX_CONCURRENCY")   # = SQLAlchemy pool (5 + 10)
    db_breaker_seconds: float = Field(default=5.0, validation_alias="DB_BREAKER_SECONDS")
    cors_origins: str = Field(default="*", validation_alias="CORS_ORIGINS")
    enable_debug_endpoints: bool = Field(default=True, validation_alias="ENABLE_DEBUG_ENDPOINTS")
    
    # Write Buffer settings
    write_buffer_size: int = Field(default=100, validation_alias="WRITE_BUFFER_SIZE")
    write_buffer_flush_interval_seconds: int = Field(default=10, validation_alias="WRITE_BUFFER_FLUSH_INTERVAL")
    # Upper bound on distinct queries held in memory between flushes (unbounded growth = memory DoS).
    write_buffer_max_unique: int = Field(default=50_000, validation_alias="WRITE_BUFFER_MAX_UNIQUE")
    trending_lambda: float = Field(default=0.5, validation_alias="TRENDING_LAMBDA")
    trending_beta: float = Field(default=10.0, validation_alias="TRENDING_BETA")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Settings() re-reads the environment and parses .env on construction; doing that per request cost
    # ~21% of the CPU of a cache-hit request. Call get_settings.cache_clear() after changing the environment.
    return Settings()
