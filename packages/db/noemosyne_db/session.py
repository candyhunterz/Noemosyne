"""Database engine and transaction factories."""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://noemosyne:noemosyne@localhost:5432/noemosyne"


def create_database_engine(url: str | None = None) -> Engine:
    """Create the canonical SQLAlchemy engine."""
    return create_engine(
        url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL), pool_pre_ping=True
    )


engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def session_scope() -> Iterator[Session]:
    """Yield one request-owned session; callers own commit/rollback semantics."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
