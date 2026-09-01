from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from noemosyne_db.seed import import_seed
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

PGVECTOR_IMAGE = (
    "pgvector/pgvector:pg18@sha256:2ba9ca5f2e7daa0f0e7723cba1ee9167bab54efd3640516a44ac1a928dd67e7a"
)


@pytest.mark.postgres
def test_fresh_postgres_migration_seed_and_append_only_constraints() -> None:
    with PostgresContainer(PGVECTOR_IMAGE, driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        engine = create_engine(database_url)
        with Session(engine) as session:
            first = import_seed(session, Path("examples/ai-research/seed.yaml"))
            second = import_seed(session, Path("examples/ai-research/seed.yaml"))
            assert first["status"] == "imported"
            assert second["status"] == "noop"

        with engine.connect() as connection:
            required_table_count = connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name <> 'alembic_version'"
                )
            )
            assert required_table_count == 31
            connection.commit()
            with pytest.raises(DBAPIError, match="append-only"):
                connection.execute(
                    text(
                        "UPDATE claims SET status='superseded' "
                        "WHERE id='e9016e40-01b5-530a-ba4e-77ff463bb617'"
                    )
                )
            connection.rollback()
        engine.dispose()
