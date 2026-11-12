"""Database connection (SQLAlchemy 2.x).

Production uses Postgres on Supabase via DATABASE_URL. Tests use in-memory
SQLite and never reach Supabase. When DATABASE_URL is not set, persistence is
simply off: uploads and exports work as before and nothing is stored.

What is stored (issue #25): protocol identification fields, the extracted
plan, and review decisions. What is never stored: the uploaded PDF and its
raw text. There is no column that could hold them.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

_engine: Optional[Engine] = None
_engine_url: Optional[str] = None


def database_url() -> Optional[str]:
    """The configured URL in the form SQLAlchemy needs, or None if unset."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    # Supabase gives "postgresql://...". SQLAlchemy needs to be told which
    # driver to use; we install psycopg (v3).
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def is_configured() -> bool:
    return database_url() is not None


def get_engine() -> Optional[Engine]:
    """One engine (connection pool) per process, rebuilt if the URL changes."""
    global _engine, _engine_url
    url = database_url()
    if url is None:
        return None
    if _engine is None or url != _engine_url:
        if url.startswith("sqlite"):
            # In-memory SQLite exists per connection, so tests share a single
            # connection across threads (StaticPool).
            _engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
        else:
            # pool_pre_ping checks a connection is alive before using it;
            # hosted Postgres closes idle connections.
            _engine = create_engine(url, pool_pre_ping=True)
        _engine_url = url
    return _engine


def reset_engine() -> None:
    """Forget the cached engine (used by tests)."""
    global _engine, _engine_url
    if _engine is not None:
        _engine.dispose()
    _engine, _engine_url = None, None


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session that commits on success and rolls back on any error."""
    engine = get_engine()
    if engine is None:
        raise RuntimeError("DATABASE_URL is not set")
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
