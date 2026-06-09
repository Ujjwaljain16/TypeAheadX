from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    database_url: str = Field("postgresql+psycopg://postgres:postgres@localhost:5433/typeaheadx", validation_alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379", validation_alias="REDIS_URL")
    cache_ttl_seconds: int = Field(default=300, validation_alias="CACHE_TTL_SECONDS")
    cache_provider: str = Field(default="memory", validation_alias="CACHE_PROVIDER")
    max_prefix_length: int = Field(64, validation_alias="MAX_PREFIX_LENGTH")
    default_limit: int = Field(10, validation_alias="SUGGESTION_LIMIT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


def get_settings() -> Settings:
    return Settings()
