from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


settings = get_settings()
engine = create_engine(
    settings.database_url,
    future=True,
    pool_timeout=settings.db_pool_timeout_seconds,           # wait at most this long for a free connection
    pool_recycle=1800,                                        # do not reuse connections older than 30 min
    connect_args={"connect_timeout": settings.db_connect_timeout_seconds},  # bound TCP connect / auth
)
SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
