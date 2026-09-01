from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
for source in (
    "apps/api",
    "apps/worker",
    "packages/domain",
    "packages/db",
    "packages/retrieval",
    "packages/testkit",
):
    sys.path.insert(0, str(ROOT / source))

from noemosyne_db.models import Base  # noqa: E402


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db_session:
        yield db_session
    Base.metadata.drop_all(engine)
