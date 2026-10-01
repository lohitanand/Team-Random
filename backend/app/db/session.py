"""SQLAlchemy engine and session factory.

Relative SQLite paths are resolved against the repo root so the app works
no matter which directory it is started from.
"""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import ROOT_DIR, get_settings

SQLITE_PREFIX = "sqlite:///"


def resolve_database_url(url: str) -> str:
    if not url.startswith(SQLITE_PREFIX) or url == f"{SQLITE_PREFIX}:memory:":
        return url
    path = Path(url.removeprefix(SQLITE_PREFIX))
    if not path.is_absolute():
        path = ROOT_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{SQLITE_PREFIX}{path.as_posix()}"


@lru_cache
def get_engine() -> Engine:
    url = resolve_database_url(get_settings().database_url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables registered on the declarative Base."""
    from backend.app.db.models import Base

    Base.metadata.create_all(get_engine())


def reset_db() -> None:
    """Drop and recreate every table (batch pipeline reruns are idempotent)."""
    from backend.app.db.models import Base

    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
