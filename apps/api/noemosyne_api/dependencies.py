"""FastAPI dependency providers."""

from collections.abc import Iterator

from noemosyne_db.session import SessionLocal
from sqlalchemy.orm import Session


def get_session() -> Iterator[Session]:
    """Provide one database session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
