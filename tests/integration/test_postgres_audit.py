from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from noemosyne_db.models import (
    Actor,
    Argument,
    ArgumentPremise,
    AssessmentPolicy,
    AuditEvent,
    Claim,
    ClaimVersion,
    Entity,
    EpistemicAssessment,
    EvidenceItem,
    EvidenceItemSource,
    EvidenceLink,
    Namespace,
    Proposal,
    ProposalItem,
    ReviewDecision,
    RevisionEvent,
    SourceArtifact,
    SourceFragment,
)
from noemosyne_db.proposals import add_review, apply_proposal, submit_proposal, validate_proposal
from noemosyne_domain.errors import ConflictError
from noemosyne_retrieval.context_bundle import build_context_bundle
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

PGVECTOR_IMAGE = (
    "pgvector/pgvector:pg18@sha256:2ba9ca5f2e7daa0f0e7723cba1ee9167bab54efd3640516a44ac1a928dd67e7a"
)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    with PostgresContainer(PGVECTOR_IMAGE, driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        engine = create_engine(database_url)
        yield engine
        engine.dispose()


def _identity() -> str:
    return str(uuid4())


def _terminal_workflow_fixture(
    session: Session, status: str = "accepted"
) -> tuple[Proposal, ProposalItem, Actor]:
    suffix = _identity()
    namespace = Namespace(slug=f"terminal-{suffix}", name="Terminal workflow")
    session.add(namespace)
    session.flush()
    proposer = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="Terminal proposer",
        external_id=f"terminal-proposer-{suffix}",
    )
    reviewer = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="Terminal reviewer",
        external_id=f"terminal-reviewer-{suffix}",
    )
    session.add_all([proposer, reviewer])
    session.flush()
    proposal = Proposal(
        namespace_id=namespace.id,
        proposer_actor_id=proposer.id,
        title=f"Terminal {status}",
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
        payload_json={"terminal_status": status},
        status="valid",
    )
    session.add(item)
    session.flush()
    session.add(
        ReviewDecision(
            proposal_item_id=item.id,
            reviewer_actor_id=reviewer.id,
            decision="reject" if status == "rejected" else "accept",
            rationale="Terminal workflow fixture",
        )
    )
    session.flush()
    item.status = "rejected" if status == "rejected" else status
    if status == "partially_accepted":
        item.status = "accepted"
    session.flush()
    proposal.status = status
    if status != "stale":
        proposal.applied_at = datetime.now(UTC)
        proposal.applied_by_actor_id = reviewer.id
    session.commit()
    return proposal, item, reviewer


def _claim_state(session: Session, slug: str):
    namespace = Namespace(slug=slug, name=slug)
    session.add(namespace)
    session.flush()
    proposer = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name=f"{slug} proposer",
        external_id=f"{slug}-p",
    )
    reviewer = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name=f"{slug} reviewer",
        external_id=f"{slug}-r",
    )
    session.add_all([proposer, reviewer])
    session.flush()
    provenance_proposal = Proposal(
        namespace_id=namespace.id,
        proposer_actor_id=proposer.id,
        title=f"Synthetic accepted fixture {slug}",
        base_revision_token=0,
        status="in_review",
        submitted_at=datetime.now(UTC),
    )
    session.add(provenance_proposal)
    session.flush()
    provenance_item = ProposalItem(
        proposal_id=provenance_proposal.id,
        position=0,
        command_type="TestFixture",
        payload_json={"fixture": slug},
        status="valid",
    )
    session.add(provenance_item)
    session.flush()
    session.add(
        ReviewDecision(
            proposal_item_id=provenance_item.id,
            reviewer_actor_id=reviewer.id,
            decision="accept",
            rationale="Synthetic fixture provenance",
        )
    )
    session.flush()
    provenance_item.status = "accepted"
    session.flush()
    provenance_proposal.status = "accepted"
    provenance_proposal.applied_at = datetime.now(UTC)
    provenance_proposal.applied_by_actor_id = reviewer.id
    session.flush()
    claim_id, version_id = _identity(), _identity()
    claim = Claim(
        id=claim_id,
        namespace_id=namespace.id,
        current_version_id=version_id,
        status="accepted",
        proposal_item_id=provenance_item.id,
    )
    version = ClaimVersion(
        id=version_id,
        claim_id=claim_id,
        version_number=1,
        wording=f"Initial {slug} wording",
        scope_json={"fixture": slug},
        valid_from=datetime(2025, 1, 1, tzinfo=UTC),
        status="accepted",
        proposal_item_id=provenance_item.id,
    )
    session.add_all([claim, version])
    session.commit()
    return namespace, proposer, reviewer, claim, version, provenance_item


def _submitted_claim_proposal(
    session: Session,
    namespace: Namespace,
    proposer: Actor,
    *,
    title: str,
    item_count: int = 1,
    base_revision_token: int | None = None,
) -> tuple[Proposal, list[ProposalItem]]:
    proposal = Proposal(
        namespace_id=namespace.id,
        proposer_actor_id=proposer.id,
        title=title,
        base_revision_token=(
            namespace.revision_token if base_revision_token is None else base_revision_token
        ),
    )
    session.add(proposal)
    session.flush()
    items = [
        ProposalItem(
            proposal_id=proposal.id,
            position=position,
            command_type="CreateClaim",
            payload_json={
                "wording": f"{title} claim {position}",
                "scope_json": {"position": position},
                "valid_from": datetime(2025, 1, position + 1, tzinfo=UTC).isoformat(),
            },
        )
        for position in range(item_count)
    ]
    session.add_all(items)
    session.commit()
    validate_proposal(session, proposal.id)
    submit_proposal(session, proposal.id)
    return proposal, items


def _insert_entity_with_process_provenance(
    session: Session,
    *,
    proposal_status: str = "accepted",
    item_status: str = "accepted",
    decisions: tuple[str, ...] = ("accept",),
    proposal_item_reference: str = "existing",
    self_review: bool = False,
    cross_namespace_reviewer: bool = False,
    cross_namespace_entity: bool = False,
) -> Entity:
    suffix = _identity()
    namespace = Namespace(slug=f"process-{suffix}", name="Process provenance")
    other_namespace = Namespace(slug=f"process-other-{suffix}", name="Other process")
    session.add_all([namespace, other_namespace])
    session.flush()
    proposer = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="Process proposer",
        external_id=f"process-proposer-{suffix}",
    )
    reviewer = Actor(
        namespace_id=other_namespace.id if cross_namespace_reviewer else namespace.id,
        kind="human",
        display_name="Process reviewer",
        external_id=f"process-reviewer-{suffix}",
    )
    session.add_all([proposer, reviewer])
    session.flush()
    proposal = Proposal(
        namespace_id=namespace.id,
        proposer_actor_id=proposer.id,
        title="Process provenance candidate",
        base_revision_token=0,
        status="in_review",
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
    for decision in decisions:
        session.add(
            ReviewDecision(
                proposal_item_id=item.id,
                reviewer_actor_id=proposer.id if self_review else reviewer.id,
                decision=decision,
                rationale=f"Process provenance {decision}",
            )
        )
    session.flush()
    item.status = item_status
    session.flush()
    proposal.status = proposal_status
    if proposal_status in {"accepted", "partially_accepted", "rejected"}:
        proposal.applied_at = datetime.now(UTC)
        proposal.applied_by_actor_id = reviewer.id
    session.flush()
    item_reference = {
        "existing": item.id,
        "missing": _identity(),
        "null": None,
    }[proposal_item_reference]
    entity = Entity(
        namespace_id=other_namespace.id if cross_namespace_entity else namespace.id,
        kind="concept",
        canonical_name=f"Process entity {suffix}",
        status="accepted",
        proposal_item_id=item_reference,
    )
    session.add(entity)
    session.commit()
    return entity


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("proposal_item_reference", "message"),
    [
        ("null", "proposal[ _]item"),
        ("missing", "proposal[ _]item"),
    ],
)
def test_accepted_rows_require_an_existing_proposal_item(
    postgres_engine: Engine, proposal_item_reference: str, message: str
) -> None:
    with Session(postgres_engine) as session, pytest.raises(DBAPIError, match=message):
        _insert_entity_with_process_provenance(
            session, proposal_item_reference=proposal_item_reference
        )


@pytest.mark.postgres
@pytest.mark.parametrize("item_status", ["pending", "valid", "rejected"])
def test_accepted_rows_require_an_accepted_item(postgres_engine: Engine, item_status: str) -> None:
    with (
        Session(postgres_engine) as session,
        pytest.raises(DBAPIError, match="requires an accepted proposal item"),
    ):
        _insert_entity_with_process_provenance(session, item_status=item_status)


@pytest.mark.postgres
@pytest.mark.parametrize("proposal_status", ["draft", "in_review", "rejected"])
def test_accepted_rows_require_a_terminal_accepted_proposal(
    postgres_engine: Engine, proposal_status: str
) -> None:
    with (
        Session(postgres_engine) as session,
        pytest.raises(DBAPIError, match="terminal accepted proposal"),
    ):
        _insert_entity_with_process_provenance(session, proposal_status=proposal_status)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "decisions",
    [("abstain",), ("accept", "reject"), ("accept", "request_changes")],
)
def test_accepted_rows_require_an_effective_conservative_acceptance(
    postgres_engine: Engine, decisions: tuple[str, ...]
) -> None:
    with (
        Session(postgres_engine) as session,
        pytest.raises(DBAPIError, match="effective separated accepted review"),
    ):
        _insert_entity_with_process_provenance(session, decisions=decisions)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "invalid_provenance", ["self_review", "cross_namespace_reviewer", "cross_namespace_entity"]
)
def test_process_provenance_preserves_separation_and_namespace(
    postgres_engine: Engine, invalid_provenance: str
) -> None:
    expected = (
        "proposer cannot review their own proposal"
        if invalid_provenance == "self_review"
        else "reviewer must belong to the proposal namespace"
        if invalid_provenance == "cross_namespace_reviewer"
        else "provenance namespace mismatch"
    )
    with Session(postgres_engine) as session, pytest.raises(DBAPIError, match=expected):
        _insert_entity_with_process_provenance(
            session,
            self_review=invalid_provenance == "self_review",
            cross_namespace_reviewer=invalid_provenance == "cross_namespace_reviewer",
            cross_namespace_entity=invalid_provenance == "cross_namespace_entity",
        )


@pytest.mark.postgres
@pytest.mark.parametrize("proposal_status", ["accepted", "partially_accepted"])
def test_valid_terminal_process_provenance_accepts_canonical_rows(
    postgres_engine: Engine, proposal_status: str
) -> None:
    with Session(postgres_engine) as session:
        entity = _insert_entity_with_process_provenance(session, proposal_status=proposal_status)
        assert entity.proposal_item_id is not None


@pytest.mark.postgres
@pytest.mark.parametrize("terminal_status", ["accepted", "partially_accepted", "rejected", "stale"])
def test_terminal_proposals_reject_every_update_and_delete(
    postgres_engine: Engine, terminal_status: str
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session:
        proposal, _, _ = _terminal_workflow_fixture(session, terminal_status)
        proposal_id = proposal.id

    with pytest.raises(DBAPIError, match="terminal proposals are immutable"):
        with postgres_engine.begin() as connection:
            connection.execute(
                text("UPDATE proposals SET status = 'in_review' WHERE id = :id"),
                {"id": proposal_id},
            )
    with pytest.raises(DBAPIError, match="terminal proposals are immutable"):
        with postgres_engine.begin() as connection:
            connection.execute(text("DELETE FROM proposals WHERE id = :id"), {"id": proposal_id})


@pytest.mark.postgres
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_items_beneath_terminal_proposals_are_sealed(
    postgres_engine: Engine, operation: str
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session:
        _, item, _ = _terminal_workflow_fixture(session)
        item_id = item.id
    statement = (
        "UPDATE proposal_items SET status = 'rejected' WHERE id = :id"
        if operation == "update"
        else "DELETE FROM proposal_items WHERE id = :id"
    )
    with pytest.raises(
        DBAPIError,
        match=r"(proposal items under terminal proposals|submitted proposal items) are immutable",
    ):
        with postgres_engine.begin() as connection:
            connection.execute(text(statement), {"id": item_id})


@pytest.mark.postgres
@pytest.mark.parametrize("decision", ["accept", "reject", "request_changes", "abstain"])
def test_terminal_proposals_reject_late_reviews(postgres_engine: Engine, decision: str) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session:
        _, item, reviewer = _terminal_workflow_fixture(session)
        late_review = ReviewDecision(
            proposal_item_id=item.id,
            reviewer_actor_id=reviewer.id,
            decision=decision,
            rationale="Too late",
        )
        session.add(late_review)
        with pytest.raises(DBAPIError, match="only be recorded while proposal is in_review"):
            session.commit()


@pytest.mark.postgres
def test_review_insertion_remains_available_while_in_review(postgres_engine: Engine) -> None:
    suffix = _identity()
    with Session(postgres_engine, expire_on_commit=False) as session:
        namespace = Namespace(slug=f"open-review-{suffix}", name="Open review")
        session.add(namespace)
        session.flush()
        proposer = Actor(
            namespace_id=namespace.id,
            kind="human",
            display_name="Open proposer",
            external_id=f"open-proposer-{suffix}",
        )
        reviewer = Actor(
            namespace_id=namespace.id,
            kind="human",
            display_name="Open reviewer",
            external_id=f"open-reviewer-{suffix}",
        )
        session.add_all([proposer, reviewer])
        session.flush()
        proposal = Proposal(
            namespace_id=namespace.id,
            proposer_actor_id=proposer.id,
            title="Open review proposal",
            base_revision_token=0,
            status="in_review",
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
        review = ReviewDecision(
            proposal_item_id=item.id,
            reviewer_actor_id=reviewer.id,
            decision="abstain",
            rationale="Valid open review",
        )
        session.add(review)
        session.commit()
        assert session.get(ReviewDecision, review.id) is not None


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("decisions", "expected_status", "created_count"),
    [
        (("accept", "accept"), "accepted", 2),
        (("accept", "reject"), "partially_accepted", 1),
        (("reject", "reject"), "rejected", 0),
    ],
)
def test_terminal_application_results_remain_supported_and_sealed(
    postgres_engine: Engine,
    decisions: tuple[str, str],
    expected_status: str,
    created_count: int,
) -> None:
    suffix = _identity()
    with Session(postgres_engine, expire_on_commit=False) as session:
        namespace, proposer, reviewer, _, _, _ = _claim_state(session, f"terminal-apply-{suffix}")
        proposal, items = _submitted_claim_proposal(
            session,
            namespace,
            proposer,
            title=f"Terminal application {suffix}",
            item_count=2,
        )
        for item, decision in zip(items, decisions, strict=True):
            add_review(
                session,
                proposal.id,
                item.id,
                reviewer.id,
                decision,
                f"Terminal application {decision}",
            )
        result = apply_proposal(session, proposal.id, reviewer.id)
        assert result.status == expected_status
        assert sum(len(item.created_canonical_ids_json) for item in items) == created_count * 2
        terminal_status = result.status
        with pytest.raises(DBAPIError, match="terminal proposals are immutable"):
            result.status = "in_review"
            session.commit()
        session.rollback()
        session.refresh(result)
        assert result.status == terminal_status


@pytest.mark.postgres
def test_stale_application_result_is_stable_and_sealed(postgres_engine: Engine) -> None:
    suffix = _identity()
    with Session(postgres_engine, expire_on_commit=False) as session:
        namespace, proposer, reviewer, _, _, _ = _claim_state(session, f"terminal-stale-{suffix}")
        proposal, items = _submitted_claim_proposal(
            session,
            namespace,
            proposer,
            title=f"Stale application {suffix}",
            base_revision_token=namespace.revision_token + 1,
        )
        add_review(
            session,
            proposal.id,
            items[0].id,
            reviewer.id,
            "accept",
            "Accept before stale detection",
        )
        with pytest.raises(ConflictError, match="Namespace changed"):
            apply_proposal(session, proposal.id, reviewer.id)
        session.refresh(proposal)
        session.refresh(items[0])
        assert proposal.status == "stale"
        assert items[0].status == "stale"
        with pytest.raises(DBAPIError, match="terminal proposals are immutable"):
            proposal.status = "in_review"
            session.commit()
        session.rollback()
        session.refresh(proposal)
        assert proposal.status == "stale"


@pytest.mark.postgres
def test_review_apply_races_serialize_on_the_parent_proposal(postgres_engine: Engine) -> None:
    suffix = _identity()
    with Session(postgres_engine, expire_on_commit=False) as setup_session:
        namespace, proposer, reviewer, _, _, _ = _claim_state(setup_session, f"race-{suffix}")
        second_reviewer = Actor(
            namespace_id=namespace.id,
            kind="human",
            display_name="Concurrent reviewer",
            external_id=f"race-reviewer-{suffix}",
        )
        setup_session.add(second_reviewer)
        setup_session.commit()
        proposal, items = _submitted_claim_proposal(
            setup_session, namespace, proposer, title=f"Race {suffix}"
        )
        add_review(
            setup_session,
            proposal.id,
            items[0].id,
            reviewer.id,
            "accept",
            "Initial acceptance",
        )
        proposal_id = proposal.id
        item_id = items[0].id
        reviewer_id = reviewer.id
        second_reviewer_id = second_reviewer.id

    # A review that obtains the proposal lock first is visible to apply.
    with Session(postgres_engine) as blocking_review_session:
        blocking_review_session.add(
            ReviewDecision(
                proposal_item_id=item_id,
                reviewer_actor_id=second_reviewer_id,
                decision="reject",
                rationale="Concurrent blocking decision",
            )
        )
        blocking_review_session.flush()

        def apply_after_review() -> str:
            with Session(postgres_engine) as concurrent_apply_session:
                return apply_proposal(concurrent_apply_session, proposal_id, reviewer_id).status

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(apply_after_review)
            blocking_review_session.commit()
            assert future.result(timeout=10) == "rejected"

    with Session(postgres_engine) as verification_session:
        assert (
            verification_session.scalar(
                select(func.count(Claim.id)).where(Claim.proposal_item_id == item_id)
            )
            == 0
        )
        stored = verification_session.get(Proposal, proposal_id)
        assert stored is not None and stored.status == "rejected"

    # If apply owns the lock first, a late review waits and then fails on terminal state.
    with Session(postgres_engine, expire_on_commit=False) as setup_session:
        namespace, proposer, reviewer, _, _, _ = _claim_state(setup_session, f"late-race-{suffix}")
        second_reviewer = Actor(
            namespace_id=namespace.id,
            kind="human",
            display_name="Late concurrent reviewer",
            external_id=f"late-race-reviewer-{suffix}",
        )
        setup_session.add(second_reviewer)
        setup_session.commit()
        proposal, items = _submitted_claim_proposal(
            setup_session, namespace, proposer, title=f"Late race {suffix}"
        )
        add_review(
            setup_session,
            proposal.id,
            items[0].id,
            reviewer.id,
            "accept",
            "Initial acceptance",
        )
        proposal_id = proposal.id
        item_id = items[0].id
        reviewer_id = reviewer.id
        second_reviewer_id = second_reviewer.id

    def insert_late_review() -> str:
        with Session(postgres_engine) as late_review_session:
            try:
                add_review(
                    late_review_session,
                    proposal_id,
                    item_id,
                    second_reviewer_id,
                    "request_changes",
                    "Must not arrive after apply",
                )
            except ConflictError as error:
                return error.code
        return "unexpected success"

    with Session(postgres_engine) as applying_session:
        applying_session.scalar(
            select(Proposal).where(Proposal.id == proposal_id).with_for_update()
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(insert_late_review)
            assert apply_proposal(applying_session, proposal_id, reviewer_id).status == "accepted"
            assert future.result(timeout=10) == "proposal.not_in_review"

    with Session(postgres_engine) as verification_session:
        assert (
            verification_session.scalar(
                select(func.count(Claim.id)).where(Claim.proposal_item_id == item_id)
            )
            == 1
        )
        assert (
            verification_session.scalar(
                select(func.count(ReviewDecision.id)).where(
                    ReviewDecision.proposal_item_id == item_id,
                    ReviewDecision.decision == "request_changes",
                )
            )
            == 0
        )


@pytest.mark.postgres
def test_nonaccepted_candidate_can_exist_without_process_provenance(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine) as session:
        namespace = Namespace(slug=f"candidate-{_identity()}", name="Candidate namespace")
        session.add(namespace)
        session.flush()
        candidate = Entity(
            namespace_id=namespace.id,
            kind="concept",
            canonical_name="Unaccepted candidate",
            status="proposed",
            proposal_item_id=None,
        )
        session.add(candidate)
        session.commit()
        assert candidate.status == "proposed"


@pytest.mark.postgres
def test_append_only_projection_and_supersession_history(postgres_engine: Engine) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session:
        namespace, proposer, reviewer, claim, old_version, _ = _claim_state(
            session, "append-projection"
        )
        cutoff = datetime.now(UTC)
        proposal = Proposal(
            namespace_id=namespace.id,
            proposer_actor_id=proposer.id,
            title="Revise wording",
            base_revision_token=0,
        )
        session.add(proposal)
        session.flush()
        item = ProposalItem(
            proposal_id=proposal.id,
            position=0,
            command_type="AddClaimVersion",
            payload_json={
                "claim_id": claim.id,
                "wording": "Revised append-only wording",
                "scope_json": {"fixture": "append-projection", "revision": 2},
                "valid_from": datetime(2025, 2, 1, tzinfo=UTC).isoformat(),
            },
            preconditions_json={
                "claim_id": claim.id,
                "claim_current_version_id": old_version.id,
            },
        )
        session.add(item)
        session.commit()
        validate_proposal(session, proposal.id)
        submit_proposal(session, proposal.id)
        add_review(session, proposal.id, item.id, reviewer.id, "accept", "Revision is scoped")
        result = apply_proposal(session, proposal.id, reviewer.id)
        assert result.status == "accepted"
        session.refresh(claim)
        new_version = session.get(ClaimVersion, claim.current_version_id)
        assert new_version is not None
        assert new_version.supersedes_id == old_version.id
        assert session.get(ClaimVersion, old_version.id).wording == old_version.wording

        historical = build_context_bundle(
            session,
            claim.id,
            cutoff,
            datetime(2025, 3, 1, tzinfo=UTC),
        )
        current = build_context_bundle(
            session,
            claim.id,
            datetime.now(UTC) + timedelta(seconds=1),
            datetime(2025, 3, 1, tzinfo=UTC),
        )
        earlier_domain_time = build_context_bundle(
            session,
            claim.id,
            datetime.now(UTC) + timedelta(seconds=1),
            datetime(2025, 1, 15, tzinfo=UTC),
        )
        assert historical is not None and historical["claim"]["version_id"] == old_version.id
        assert current is not None and current["claim"]["version_id"] == new_version.id
        assert (
            earlier_domain_time is not None
            and earlier_domain_time["claim"]["version_id"] == old_version.id
        )

    with postgres_engine.connect() as connection:
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(
                text("UPDATE claim_versions SET wording='tampered' WHERE id=:id"),
                {"id": old_version.id},
            )
        connection.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(
                text("DELETE FROM claim_versions WHERE id=:id"),
                {"id": old_version.id},
            )
        connection.rollback()
        connection.execute(text("SET LOCAL noemosyne.accepting_proposal = 'on'"))
        connection.execute(text("SET LOCAL noemosyne.arbitrary_bypass = 'on'"))
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(
                text("UPDATE claims SET normalization_status='tampered' WHERE id=:id"),
                {"id": claim.id},
            )
        connection.rollback()


@pytest.mark.postgres
def test_postgres_evidence_provenance_constraints_and_context(postgres_engine: Engine) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session:
        namespace, proposer, _, claim, _, provenance_item = _claim_state(
            session, "evidence-provenance"
        )
        policy = AssessmentPolicy(
            namespace_id=namespace.id,
            name="Evidence policy",
            version="1",
            status="accepted",
            proposal_item_id=provenance_item.id,
        )
        source = SourceArtifact(
            namespace_id=namespace.id,
            kind="paper",
            title="Complete source",
            canonical_uri="https://example.test/complete",
            license_basis="metadata-only",
            status="accepted",
            proposal_item_id=provenance_item.id,
        )
        session.add_all([policy, source])
        session.flush()
        fragment = SourceFragment(
            source_artifact_id=source.id,
            locator_json={"section": "results"},
            stored_text="redistributable fixture text",
            text_hash="fixture-hash",
            license_basis="test-fixture-license",
            status="accepted",
            proposal_item_id=provenance_item.id,
        )
        session.add(fragment)
        session.commit()

        missing = EvidenceItem(
            namespace_id=namespace.id,
            kind="source_fragment",
            status="accepted",
            proposal_item_id=provenance_item.id,
        )
        session.add(missing)
        with pytest.raises(DBAPIError, match="resolvable provenance"):
            session.commit()
        session.rollback()

        incomplete = SourceArtifact(
            namespace_id=namespace.id,
            kind="paper",
            title="",
            canonical_uri="",
            license_basis="",
            status="accepted",
            proposal_item_id=provenance_item.id,
        )
        session.add(incomplete)
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()

        missing_hash = SourceFragment(
            source_artifact_id=source.id,
            locator_json={"section": "hash"},
            stored_text="text without a hash",
            text_hash=None,
            license_basis="test-fixture-license",
            status="accepted",
            proposal_item_id=provenance_item.id,
        )
        session.add(missing_hash)
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()

        missing_argument = EvidenceItem(
            namespace_id=namespace.id,
            kind="argument",
            argument_id=None,
            status="accepted",
            proposal_item_id=provenance_item.id,
        )
        session.add(missing_argument)
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()

        source_item = EvidenceItem(
            namespace_id=namespace.id,
            kind="source_fragment",
            status="accepted",
            proposal_item_id=provenance_item.id,
        )
        session.add(source_item)
        session.flush()
        session.add(
            EvidenceItemSource(
                evidence_item_id=source_item.id,
                source_fragment_id=fragment.id,
                status="accepted",
                proposal_item_id=provenance_item.id,
            )
        )
        argument = Argument(
            namespace_id=namespace.id,
            conclusion_claim_id=claim.id,
            author_actor_id=proposer.id,
            inference_scheme="deductive",
            rationale="An explicit argument",
            status="accepted",
            proposal_item_id=provenance_item.id,
        )
        session.add(argument)
        session.flush()
        session.add(
            ArgumentPremise(
                argument_id=argument.id,
                premise_type="claim",
                premise_id=claim.id,
                position=0,
                status="accepted",
                proposal_item_id=provenance_item.id,
            )
        )
        argument_item = EvidenceItem(
            namespace_id=namespace.id,
            kind="argument",
            argument_id=argument.id,
            status="accepted",
            proposal_item_id=provenance_item.id,
        )
        session.add(argument_item)
        session.flush()
        for evidence_item in (source_item, argument_item):
            session.add(
                EvidenceLink(
                    claim_id=claim.id,
                    evidence_item_id=evidence_item.id,
                    evaluator_actor_id=proposer.id,
                    assessment_policy_id=policy.id,
                    stance="supports",
                    directness="direct",
                    strength_band="material",
                    scope_match="Exact fixture scope",
                    status="accepted",
                    proposal_item_id=provenance_item.id,
                )
            )
        session.commit()

        bundle = build_context_bundle(
            session,
            claim.id,
            datetime.now(UTC) + timedelta(seconds=1),
            datetime.now(UTC),
        )
        assert bundle is not None
        returned = [item for group in bundle["evidence_groups"] for item in group["items"]]
        assert len(returned) == 2
        assert any(item["sources"] for item in returned)
        assert any(item["argument"] is not None for item in returned)

        namespace_b, _, _, _, _, provenance_item_b = _claim_state(session, "evidence-other")
        source_b = SourceArtifact(
            namespace_id=namespace_b.id,
            kind="paper",
            title="Other source",
            canonical_uri="https://example.test/other",
            license_basis="metadata-only",
            status="accepted",
            proposal_item_id=provenance_item_b.id,
        )
        session.add(source_b)
        session.flush()
        fragment_b = SourceFragment(
            source_artifact_id=source_b.id,
            locator_json={"section": "x"},
            license_basis="locator-only",
            status="accepted",
            proposal_item_id=provenance_item_b.id,
        )
        session.add(fragment_b)
        session.flush()
        cross_item = EvidenceItem(
            namespace_id=namespace.id,
            kind="source_fragment",
            status="accepted",
            proposal_item_id=provenance_item.id,
        )
        session.add(cross_item)
        session.flush()
        session.add(
            EvidenceItemSource(
                evidence_item_id=cross_item.id,
                source_fragment_id=fragment_b.id,
                status="accepted",
                proposal_item_id=provenance_item.id,
            )
        )
        with pytest.raises(DBAPIError, match="resolvable provenance"):
            session.commit()
        session.rollback()

        unresolved = EvidenceItem(
            namespace_id=namespace.id, kind="source_fragment", status="proposed"
        )
        session.add(unresolved)
        session.flush()
        session.add(
            EvidenceLink(
                claim_id=claim.id,
                evidence_item_id=unresolved.id,
                evaluator_actor_id=proposer.id,
                assessment_policy_id=policy.id,
                stance="supports",
                directness="direct",
                strength_band="material",
                scope_match="Invalid fixture",
                status="accepted",
                proposal_item_id=provenance_item.id,
            )
        )
        with pytest.raises(DBAPIError, match="resolvable provenance"):
            session.commit()
        session.rollback()


@pytest.mark.postgres
def test_conflicting_review_and_concurrent_identity_proposals(postgres_engine: Engine) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session:
        namespace, proposer, reviewer, claim, old_version, _ = _claim_state(
            session, "review-concurrency"
        )
        reviewer_two = Actor(
            namespace_id=namespace.id,
            kind="human",
            display_name="Second reviewer",
            external_id="review-concurrency-r2",
        )
        session.add(reviewer_two)
        session.commit()
        rejected = Proposal(
            namespace_id=namespace.id,
            proposer_actor_id=proposer.id,
            title="Rejected candidate",
            base_revision_token=0,
        )
        session.add(rejected)
        session.flush()
        rejected_item = ProposalItem(
            proposal_id=rejected.id,
            position=0,
            command_type="CreateClaim",
            payload_json={
                "wording": "Must not be created",
                "scope_json": {},
                "valid_from": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
            },
        )
        session.add(rejected_item)
        session.commit()
        validate_proposal(session, rejected.id)
        submit_proposal(session, rejected.id)
        add_review(session, rejected.id, rejected_item.id, reviewer.id, "reject", "Reject")
        add_review(session, rejected.id, rejected_item.id, reviewer_two.id, "accept", "Accept")
        assert apply_proposal(session, rejected.id, reviewer_two.id).status == "rejected"
        assert namespace.revision_token == 0

        proposals = []
        for position in (2, 3):
            proposal = Proposal(
                namespace_id=namespace.id,
                proposer_actor_id=proposer.id,
                title=f"Concurrent revision {position}",
                base_revision_token=0,
            )
            session.add(proposal)
            session.flush()
            item = ProposalItem(
                proposal_id=proposal.id,
                position=0,
                command_type="AddClaimVersion",
                payload_json={
                    "claim_id": claim.id,
                    "wording": f"Concurrent wording {position}",
                    "scope_json": {"revision": position},
                    "valid_from": datetime(2025, position, 1, tzinfo=UTC).isoformat(),
                },
                preconditions_json={
                    "claim_id": claim.id,
                    "claim_current_version_id": old_version.id,
                },
            )
            session.add(item)
            session.commit()
            validate_proposal(session, proposal.id)
            submit_proposal(session, proposal.id)
            add_review(session, proposal.id, item.id, reviewer.id, "accept", "Reviewed")
            proposals.append(proposal)
        assert apply_proposal(session, proposals[0].id, reviewer.id).status == "accepted"
        with pytest.raises(ConflictError) as stale:
            apply_proposal(session, proposals[1].id, reviewer.id)
        assert stale.value.code == "proposal.stale_base_revision"
        assert namespace.revision_token == 1

        b_namespace, b_proposer, b_reviewer, b_claim, _, _ = _claim_state(
            session, "cross-namespace-pg"
        )
        cross = Proposal(
            namespace_id=namespace.id,
            proposer_actor_id=proposer.id,
            title="Cross namespace",
            base_revision_token=1,
        )
        session.add(cross)
        session.flush()
        cross_item = ProposalItem(
            proposal_id=cross.id,
            position=0,
            command_type="AddClaimVersion",
            payload_json={
                "claim_id": b_claim.id,
                "wording": "Forbidden",
                "scope_json": {},
                "valid_from": datetime(2025, 4, 1, tzinfo=UTC).isoformat(),
            },
        )
        session.add(cross_item)
        session.commit()
        validate_proposal(session, cross.id)
        assert cross_item.status == "invalid"
        assert cross_item.validation_errors_json[0]["code"] == "reference.namespace_mismatch"
        assert namespace.revision_token == 1
        assert b_namespace.revision_token == 0
        assert b_proposer.namespace_id == b_reviewer.namespace_id == b_namespace.id


@pytest.mark.postgres
def test_assessments_form_supersession_and_revision_chains(postgres_engine: Engine) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session:
        namespace, proposer, reviewer, claim, _, provenance_item = _claim_state(
            session, "assessment-chain"
        )
        policy = AssessmentPolicy(
            namespace_id=namespace.id,
            name="Assessment chain policy",
            version="1",
            status="accepted",
            proposal_item_id=provenance_item.id,
        )
        argument = Argument(
            namespace_id=namespace.id,
            conclusion_claim_id=claim.id,
            author_actor_id=proposer.id,
            inference_scheme="deductive",
            rationale="Accepted assessment input",
            status="accepted",
            proposal_item_id=provenance_item.id,
        )
        session.add_all([policy, argument])
        session.flush()
        session.add(
            ArgumentPremise(
                argument_id=argument.id,
                premise_type="claim",
                premise_id=claim.id,
                position=0,
                status="accepted",
                proposal_item_id=provenance_item.id,
            )
        )
        session.commit()

        def apply_assessment(base_token: int, verdict: str, valid_from: datetime) -> None:
            proposal = Proposal(
                namespace_id=namespace.id,
                proposer_actor_id=proposer.id,
                title=f"Assessment {verdict}",
                base_revision_token=base_token,
            )
            session.add(proposal)
            session.flush()
            item = ProposalItem(
                proposal_id=proposal.id,
                position=0,
                command_type="CreateAssessment",
                payload_json={
                    "claim_id": claim.id,
                    "assessor_actor_id": proposer.id,
                    "policy_id": policy.id,
                    "verdict": verdict,
                    "rationale": f"Assessment rationale for {verdict}",
                    "input_type": "argument",
                    "input_ids": [argument.id],
                    "valid_from": valid_from.isoformat(),
                },
            )
            session.add(item)
            session.commit()
            validate_proposal(session, proposal.id)
            submit_proposal(session, proposal.id)
            add_review(session, proposal.id, item.id, reviewer.id, "accept", "Chain reviewed")
            assert apply_proposal(session, proposal.id, reviewer.id).status == "accepted"

        apply_assessment(0, "provisionally_supported", datetime(2025, 1, 1, tzinfo=UTC))
        first = session.scalar(
            select(EpistemicAssessment)
            .where(EpistemicAssessment.claim_id == claim.id)
            .order_by(EpistemicAssessment.recorded_at.desc())
        )
        assert first is not None and first.supersedes_id is None
        first_cutoff = datetime.now(UTC)
        apply_assessment(1, "well_supported", datetime(2025, 2, 1, tzinfo=UTC))
        assessments = session.scalars(
            select(EpistemicAssessment)
            .where(EpistemicAssessment.claim_id == claim.id)
            .order_by(EpistemicAssessment.recorded_at)
        ).all()
        assert len(assessments) == 2
        second = assessments[1]
        assert second.supersedes_id == first.id
        revisions = session.scalars(
            select(RevisionEvent)
            .where(RevisionEvent.claim_id == claim.id)
            .order_by(RevisionEvent.recorded_at)
        ).all()
        assert [(row.before_assessment_id, row.after_assessment_id) for row in revisions] == [
            (None, first.id),
            (first.id, second.id),
        ]
        historical = build_context_bundle(
            session, claim.id, first_cutoff, datetime(2025, 3, 1, tzinfo=UTC)
        )
        current = build_context_bundle(
            session,
            claim.id,
            datetime.now(UTC) + timedelta(seconds=1),
            datetime(2025, 3, 1, tzinfo=UTC),
        )
        assert historical is not None
        assert historical["assessment"]["id"] == first.id
        assert current is not None
        assert current["assessment"]["id"] == second.id


@pytest.mark.postgres
def test_failed_postgres_application_rolls_back_canonical_and_audit_effects(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session:
        namespace, proposer, reviewer, _, _, _ = _claim_state(session, "rollback-pg")
        proposal = Proposal(
            namespace_id=namespace.id,
            proposer_actor_id=proposer.id,
            title="Rollback duplicate source transaction",
            base_revision_token=0,
        )
        session.add(proposal)
        session.flush()
        items = []
        for position in range(2):
            item = ProposalItem(
                proposal_id=proposal.id,
                position=position,
                command_type="RegisterSourceArtifact",
                payload_json={
                    "id": _identity(),
                    "title": f"Rollback source {position}",
                    "kind": "paper",
                    "canonical_uri": "https://example.test/rollback-duplicate",
                    "content_hash": "duplicate-hash",
                    "license_basis": "metadata-only",
                },
            )
            session.add(item)
            items.append(item)
        session.commit()
        validate_proposal(session, proposal.id)
        submit_proposal(session, proposal.id)
        for item in items:
            add_review(session, proposal.id, item.id, reviewer.id, "accept", "Reviewed")
        with pytest.raises(IntegrityError):
            apply_proposal(session, proposal.id, reviewer.id)
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceArtifact)
                .where(SourceArtifact.canonical_uri == "https://example.test/rollback-duplicate")
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.proposal_id == proposal.id)
            )
            == 0
        )
        session.refresh(namespace)
        assert namespace.revision_token == 0
