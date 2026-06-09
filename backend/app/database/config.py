from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    database_url: str = Field("postgresql+psycopg://postgres:postgres@localhost:5433/typeaheadx", validation_alias="DATABASE_URL")
    max_prefix_length: int = Field(64, validation_alias="MAX_PREFIX_LENGTH")
    default_limit: int = Field(10, validation_alias="SUGGESTION_LIMIT")

    model_config = {
        "env_file": "./backend/.env",
        "extra": "ignore"
    }


def get_settings() -> Settings:
    return Settings()
