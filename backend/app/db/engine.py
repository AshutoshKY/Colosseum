"""SQLModel/SQLAlchemy engine + session helpers.

Synchronous engine is sufficient for Phase 1 persistence (the gateway is async; DB writes
are quick and wrapped in a thread-friendly session scope). Offline tests pass an in-memory
SQLite URL.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine

# Importing the models package registers all tables on SQLModel.metadata.
import app.models  # noqa: F401
from app.core.config import get_settings

_engine: Engine | None = None


def get_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Return (and cache) the process-wide engine.

    Passing an explicit ``url`` (e.g. ``sqlite://``) bypasses the cache and returns a
    fresh engine — used by tests.
    """
    global _engine
    if url is not None:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        return create_engine(url, echo=echo, connect_args=connect_args)
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(settings.database_url, echo=echo, pool_pre_ping=True)
    return _engine


def create_all(engine: Engine | None = None) -> None:
    """Create all tables (used by tests / first-run bootstrap; prod uses Alembic)."""
    SQLModel.metadata.create_all(engine or get_engine())


def get_session(engine: Engine | None = None) -> Session:
    return Session(engine or get_engine())


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Transactional session scope: commit on success, rollback on error."""
    session = get_session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
