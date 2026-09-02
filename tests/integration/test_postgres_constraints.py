from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from noemosyne_db.models import Actor, Entity, Namespace, Proposal, ProposalItem, ReviewDecision
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
            process_trigger_count = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE tgname LIKE '%_process_provenance' AND NOT tgisinternal"
                )
            )
            assert process_trigger_count == 24
            seal_trigger_count = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE tgname IN ('proposals_seal_terminal', "
                    "'proposal_items_seal_terminal') AND NOT tgisinternal"
                )
            )
            assert seal_trigger_count == 2
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


@pytest.mark.postgres
def test_terminal_seal_migration_rejects_preexisting_invalid_provenance() -> None:
    with PostgresContainer(PGVECTOR_IMAGE, driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "0004_process_provenance")
        engine = create_engine(database_url)
        suffix = str(uuid4())
        with Session(engine) as session:
            namespace = Namespace(slug=f"upgrade-{suffix}", name="Upgrade safety")
            session.add(namespace)
            session.flush()
            proposer = Actor(
                namespace_id=namespace.id,
                kind="human",
                display_name="Upgrade proposer",
                external_id=f"upgrade-proposer-{suffix}",
            )
            reviewer = Actor(
                namespace_id=namespace.id,
                kind="human",
                display_name="Upgrade reviewer",
                external_id=f"upgrade-reviewer-{suffix}",
            )
            session.add_all([proposer, reviewer])
            session.flush()
            proposal = Proposal(
                namespace_id=namespace.id,
                proposer_actor_id=proposer.id,
                title="Upgrade safety provenance",
                base_revision_token=0,
                status="in_review",
                submitted_at=datetime.now(UTC),
            )
            session.add(proposal)
            session.flush()
            item = ProposalItem(
                proposal_id=proposal.id,
                position=0,
                command_type="TestFixture",
                payload_json={},
                status="valid",
            )
            session.add(item)
            session.flush()
            session.add(
                ReviewDecision(
                    proposal_item_id=item.id,
                    reviewer_actor_id=reviewer.id,
                    decision="accept",
                    rationale="Valid before provenance is corrupted",
                )
            )
            session.flush()
            item.status = "accepted"
            session.flush()
            proposal.status = "accepted"
            proposal.applied_at = datetime.now(UTC)
            proposal.applied_by_actor_id = reviewer.id
            session.flush()
            session.add(
                Entity(
                    namespace_id=namespace.id,
                    kind="concept",
                    canonical_name="Accepted before corruption",
                    status="accepted",
                    proposal_item_id=item.id,
                )
            )
            session.commit()
            proposal.status = "rejected"
            session.commit()

        with pytest.raises(DBAPIError, match="terminal accepted proposal"):
            command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0004_process_provenance"
            )
        engine.dispose()
