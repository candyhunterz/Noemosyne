from __future__ import annotations

from collections.abc import Iterator
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
    EpistemicAssessment,
    EvidenceItem,
    EvidenceItemSource,
    EvidenceLink,
    Namespace,
    Proposal,
    ProposalItem,
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
    claim_id, version_id = _identity(), _identity()
    claim = Claim(
        id=claim_id,
        namespace_id=namespace.id,
        current_version_id=version_id,
        status="accepted",
    )
    version = ClaimVersion(
        id=version_id,
        claim_id=claim_id,
        version_number=1,
        wording=f"Initial {slug} wording",
        scope_json={"fixture": slug},
        valid_from=datetime(2025, 1, 1, tzinfo=UTC),
        status="accepted",
    )
    session.add_all([claim, version])
    session.commit()
    return namespace, proposer, reviewer, claim, version


@pytest.mark.postgres
def test_append_only_projection_and_supersession_history(postgres_engine: Engine) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session:
        namespace, proposer, reviewer, claim, old_version = _claim_state(
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
        namespace, proposer, _, claim, _ = _claim_state(session, "evidence-provenance")
        policy = AssessmentPolicy(
            namespace_id=namespace.id,
            name="Evidence policy",
            version="1",
            status="accepted",
        )
        source = SourceArtifact(
            namespace_id=namespace.id,
            kind="paper",
            title="Complete source",
            canonical_uri="https://example.test/complete",
            license_basis="metadata-only",
            status="accepted",
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
        )
        session.add(fragment)
        session.commit()

        missing = EvidenceItem(namespace_id=namespace.id, kind="source_fragment", status="accepted")
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
        )
        session.add(missing_argument)
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()

        source_item = EvidenceItem(
            namespace_id=namespace.id, kind="source_fragment", status="accepted"
        )
        session.add(source_item)
        session.flush()
        session.add(
            EvidenceItemSource(
                evidence_item_id=source_item.id,
                source_fragment_id=fragment.id,
                status="accepted",
            )
        )
        argument = Argument(
            namespace_id=namespace.id,
            conclusion_claim_id=claim.id,
            author_actor_id=proposer.id,
            inference_scheme="deductive",
            rationale="An explicit argument",
            status="accepted",
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
            )
        )
        argument_item = EvidenceItem(
            namespace_id=namespace.id,
            kind="argument",
            argument_id=argument.id,
            status="accepted",
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

        namespace_b = Namespace(slug="evidence-other", name="Evidence other")
        session.add(namespace_b)
        session.flush()
        source_b = SourceArtifact(
            namespace_id=namespace_b.id,
            kind="paper",
            title="Other source",
            canonical_uri="https://example.test/other",
            license_basis="metadata-only",
            status="accepted",
        )
        session.add(source_b)
        session.flush()
        fragment_b = SourceFragment(
            source_artifact_id=source_b.id,
            locator_json={"section": "x"},
            license_basis="locator-only",
            status="accepted",
        )
        session.add(fragment_b)
        session.flush()
        cross_item = EvidenceItem(
            namespace_id=namespace.id, kind="source_fragment", status="accepted"
        )
        session.add(cross_item)
        session.flush()
        session.add(
            EvidenceItemSource(
                evidence_item_id=cross_item.id,
                source_fragment_id=fragment_b.id,
                status="accepted",
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
            )
        )
        with pytest.raises(DBAPIError, match="resolvable provenance"):
            session.commit()
        session.rollback()


@pytest.mark.postgres
def test_conflicting_review_and_concurrent_identity_proposals(postgres_engine: Engine) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session:
        namespace, proposer, reviewer, claim, old_version = _claim_state(
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

        b_namespace, b_proposer, b_reviewer, b_claim, _ = _claim_state(
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
        namespace, proposer, reviewer, claim, _ = _claim_state(session, "assessment-chain")
        policy = AssessmentPolicy(
            namespace_id=namespace.id,
            name="Assessment chain policy",
            version="1",
            status="accepted",
        )
        argument = Argument(
            namespace_id=namespace.id,
            conclusion_claim_id=claim.id,
            author_actor_id=proposer.id,
            inference_scheme="deductive",
            rationale="Accepted assessment input",
            status="accepted",
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
        namespace, proposer, reviewer, _, _ = _claim_state(session, "rollback-pg")
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
