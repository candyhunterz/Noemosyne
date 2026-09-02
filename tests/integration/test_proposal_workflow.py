from datetime import UTC, datetime

import pytest
from noemosyne_db.models import (
    Actor,
    AuditEvent,
    Claim,
    Namespace,
    Proposal,
    ProposalItem,
    SourceArtifact,
)
from noemosyne_db.proposals import add_review, apply_proposal, submit_proposal, validate_proposal
from noemosyne_domain.errors import ConflictError, DomainError
from sqlalchemy.exc import IntegrityError


def setup_proposal(session):
    namespace = Namespace(slug="test", name="Test")
    session.add(namespace)
    session.flush()
    proposer = Actor(
        namespace_id=namespace.id, kind="human", display_name="Proposer", external_id="p"
    )
    reviewer = Actor(
        namespace_id=namespace.id, kind="human", display_name="Reviewer", external_id="r"
    )
    session.add_all([proposer, reviewer])
    session.flush()
    proposal = Proposal(
        namespace_id=namespace.id,
        proposer_actor_id=proposer.id,
        title="Create a narrow claim",
        base_revision_token=0,
    )
    session.add(proposal)
    session.flush()
    item = ProposalItem(
        proposal_id=proposal.id,
        position=0,
        command_type="CreateClaim",
        payload_json={
            "wording": "A narrowly scoped claim.",
            "scope_json": {"benchmark": "fixture-v1"},
            "valid_from": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
        },
    )
    session.add(item)
    session.commit()
    return namespace, proposer, reviewer, proposal, item


def test_proposal_apply_is_reviewed_atomic_and_idempotent(session) -> None:
    namespace, _, reviewer, proposal, item = setup_proposal(session)
    retry_actor = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="Retry actor",
        external_id="retry-actor",
    )
    session.add(retry_actor)
    session.commit()
    validate_proposal(session, proposal.id)
    submit_proposal(session, proposal.id)
    add_review(
        session, proposal.id, item.id, reviewer.id, "accept", "Scope and provenance are explicit"
    )
    result = apply_proposal(session, proposal.id, reviewer.id)
    assert result.status == "accepted"
    assert namespace.revision_token == 1
    original_applied_at = result.applied_at
    original_created_ids = list(item.created_canonical_ids_json)
    original_counts = (
        session.query(Claim).count(),
        session.query(AuditEvent).count(),
    )

    retry = apply_proposal(session, proposal.id, retry_actor.id)

    assert retry.id == result.id
    assert namespace.revision_token == 1
    assert retry.applied_at == original_applied_at
    assert retry.applied_by_actor_id == reviewer.id
    assert item.created_canonical_ids_json == original_created_ids
    assert (session.query(Claim).count(), session.query(AuditEvent).count()) == original_counts


def test_partially_accepted_proposal_retry_preserves_original_result(session) -> None:
    namespace, _, reviewer, proposal, accepted_item = setup_proposal(session)
    rejected_item = ProposalItem(
        proposal_id=proposal.id,
        position=1,
        command_type="CreateClaim",
        payload_json={
            "wording": "A rejected companion claim.",
            "scope_json": {"fixture": "rejected"},
            "valid_from": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
        },
    )
    retry_actor = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="Partial retry actor",
        external_id="partial-retry",
    )
    session.add_all([rejected_item, retry_actor])
    session.commit()
    validate_proposal(session, proposal.id)
    submit_proposal(session, proposal.id)
    add_review(session, proposal.id, accepted_item.id, reviewer.id, "accept", "Accepted")
    add_review(session, proposal.id, rejected_item.id, reviewer.id, "reject", "Rejected")
    result = apply_proposal(session, proposal.id, reviewer.id)
    snapshot = (
        result.applied_at,
        result.applied_by_actor_id,
        namespace.revision_token,
        session.query(Claim).count(),
        session.query(AuditEvent).count(),
        tuple(accepted_item.created_canonical_ids_json),
    )

    retry = apply_proposal(session, proposal.id, retry_actor.id)

    assert retry.status == "partially_accepted"
    assert (
        retry.applied_at,
        retry.applied_by_actor_id,
        namespace.revision_token,
        session.query(Claim).count(),
        session.query(AuditEvent).count(),
        tuple(accepted_item.created_canonical_ids_json),
    ) == snapshot


def test_rejected_proposal_retry_is_terminal_and_write_free(session) -> None:
    namespace, _, reviewer, proposal, item = setup_proposal(session)
    retry_actor = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="Rejected retry actor",
        external_id="rejected-retry",
    )
    session.add(retry_actor)
    session.commit()
    validate_proposal(session, proposal.id)
    submit_proposal(session, proposal.id)
    add_review(session, proposal.id, item.id, reviewer.id, "reject", "Not accepted")
    result = apply_proposal(session, proposal.id, reviewer.id)
    snapshot = (
        result.applied_at,
        result.applied_by_actor_id,
        namespace.revision_token,
        session.query(Claim).count(),
        session.query(AuditEvent).count(),
        tuple(item.created_canonical_ids_json),
    )

    retry = apply_proposal(session, proposal.id, retry_actor.id)

    assert retry.status == "rejected"
    assert (
        retry.applied_at,
        retry.applied_by_actor_id,
        namespace.revision_token,
        session.query(Claim).count(),
        session.query(AuditEvent).count(),
        tuple(item.created_canonical_ids_json),
    ) == snapshot


def test_proposer_cannot_review_own_item(session) -> None:
    _, proposer, _, proposal, item = setup_proposal(session)
    validate_proposal(session, proposal.id)
    submit_proposal(session, proposal.id)
    with pytest.raises(DomainError, match="cannot review"):
        add_review(session, proposal.id, item.id, proposer.id, "accept", "Self approval")


def test_stale_base_rolls_back_canonical_side_effects(session) -> None:
    namespace, _, reviewer, proposal, item = setup_proposal(session)
    validate_proposal(session, proposal.id)
    submit_proposal(session, proposal.id)
    add_review(session, proposal.id, item.id, reviewer.id, "accept", "Reviewed")
    namespace.revision_token = 2
    session.commit()
    with pytest.raises(ConflictError) as first:
        apply_proposal(session, proposal.id, reviewer.id)
    assert first.value.code == "proposal.stale_base_revision"
    restored = session.get(Proposal, proposal.id)
    assert restored is not None
    assert restored.status == "stale"
    snapshot = (
        restored.applied_at,
        restored.applied_by_actor_id,
        namespace.revision_token,
        session.query(Claim).count(),
        session.query(AuditEvent).count(),
    )
    with pytest.raises(ConflictError) as retry:
        apply_proposal(session, proposal.id, reviewer.id)
    assert retry.value.code == "proposal.stale_base_revision"
    assert (
        restored.applied_at,
        restored.applied_by_actor_id,
        namespace.revision_token,
        session.query(Claim).count(),
        session.query(AuditEvent).count(),
    ) == snapshot


def test_failed_accepted_item_rolls_back_all_canonical_writes(session) -> None:
    _, _, reviewer, proposal, _ = setup_proposal(session)
    session.query(ProposalItem).filter_by(proposal_id=proposal.id).delete()
    first_item = ProposalItem(
        proposal_id=proposal.id,
        position=0,
        command_type="RegisterSourceArtifact",
        payload_json={
            "id": "10000000-0000-0000-0000-000000000001",
            "title": "First source",
            "kind": "paper",
            "canonical_uri": "https://example.test/duplicate",
            "license_basis": "metadata-only",
            "content_hash": "same-hash",
        },
    )
    second_item = ProposalItem(
        proposal_id=proposal.id,
        position=1,
        command_type="RegisterSourceArtifact",
        payload_json={
            "id": "10000000-0000-0000-0000-000000000002",
            "title": "Conflicting source",
            "kind": "paper",
            "canonical_uri": "https://example.test/duplicate",
            "license_basis": "metadata-only",
            "content_hash": "same-hash",
        },
    )
    session.add_all([first_item, second_item])
    session.commit()
    validate_proposal(session, proposal.id)
    submit_proposal(session, proposal.id)
    add_review(session, proposal.id, first_item.id, reviewer.id, "accept", "Reviewed")
    add_review(session, proposal.id, second_item.id, reviewer.id, "accept", "Reviewed")
    with pytest.raises(IntegrityError):
        apply_proposal(session, proposal.id, reviewer.id)
    assert session.query(SourceArtifact).count() == 0
    assert session.query(AuditEvent).count() == 0
    assert session.get(Proposal, proposal.id).status == "in_review"
    with pytest.raises(IntegrityError):
        apply_proposal(session, proposal.id, reviewer.id)
    assert session.query(SourceArtifact).count() == 0
    assert session.query(AuditEvent).count() == 0


def test_conservative_reviews_do_not_allow_later_acceptance_to_erase_rejection(session) -> None:
    namespace, _, reviewer, proposal, item = setup_proposal(session)
    second_reviewer = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="Second reviewer",
        external_id="r2",
    )
    session.add(second_reviewer)
    session.commit()
    validate_proposal(session, proposal.id)
    submit_proposal(session, proposal.id)
    add_review(session, proposal.id, item.id, reviewer.id, "reject", "Scope is not justified")
    add_review(
        session,
        proposal.id,
        item.id,
        second_reviewer.id,
        "accept",
        "The syntax is valid",
    )

    result = apply_proposal(session, proposal.id, second_reviewer.id)

    assert result.status == "rejected"
    assert item.status == "rejected"
    assert session.query(Claim).count() == 0
    assert namespace.revision_token == 0


@pytest.mark.parametrize("blocking_decision", ["request_changes", "reject"])
def test_blocking_review_outcomes_create_no_canonical_state(
    session, blocking_decision: str
) -> None:
    namespace, _, reviewer, proposal, item = setup_proposal(session)
    validate_proposal(session, proposal.id)
    submit_proposal(session, proposal.id)
    add_review(
        session,
        proposal.id,
        item.id,
        reviewer.id,
        blocking_decision,
        "The candidate is not acceptable as submitted",
    )
    assert apply_proposal(session, proposal.id, reviewer.id).status == "rejected"
    assert session.query(Claim).count() == 0
    assert namespace.revision_token == 0


def test_abstention_does_not_authorize_application(session) -> None:
    namespace, _, reviewer, proposal, item = setup_proposal(session)
    validate_proposal(session, proposal.id)
    submit_proposal(session, proposal.id)
    add_review(session, proposal.id, item.id, reviewer.id, "abstain", "Outside my expertise")
    with pytest.raises(DomainError) as raised:
        apply_proposal(session, proposal.id, reviewer.id)
    assert raised.value.code == "review.substantive_decision_required"
    assert session.query(Claim).count() == 0
    assert namespace.revision_token == 0
