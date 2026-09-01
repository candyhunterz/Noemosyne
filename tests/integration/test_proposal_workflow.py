from datetime import UTC, datetime

import pytest
from noemosyne_db.models import Actor, Claim, Namespace, Proposal, ProposalItem
from noemosyne_db.proposals import add_review, apply_proposal, submit_proposal, validate_proposal
from noemosyne_domain.errors import ConflictError, DomainError


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
    validate_proposal(session, proposal.id)
    submit_proposal(session, proposal.id)
    add_review(
        session, proposal.id, item.id, reviewer.id, "accept", "Scope and provenance are explicit"
    )
    result = apply_proposal(session, proposal.id, reviewer.id)
    assert result.status == "accepted"
    assert namespace.revision_token == 1
    assert apply_proposal(session, proposal.id, reviewer.id).id == result.id
    assert namespace.revision_token == 1


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
    with pytest.raises(ConflictError):
        apply_proposal(session, proposal.id, reviewer.id)
    restored = session.get(Proposal, proposal.id)
    assert restored is not None
    assert restored.status == "stale"


def test_failed_accepted_item_rolls_back_all_canonical_writes(session) -> None:
    _, _, reviewer, proposal, first_item = setup_proposal(session)
    second_item = ProposalItem(
        proposal_id=proposal.id,
        position=1,
        command_type="AddClaimVersion",
        payload_json={
            "claim_id": "00000000-0000-0000-0000-000000000000",
            "wording": "This target does not exist.",
            "scope_json": {"fixture": "rollback"},
            "valid_from": datetime(2025, 1, 2, tzinfo=UTC).isoformat(),
        },
    )
    session.add(second_item)
    session.commit()
    validate_proposal(session, proposal.id)
    submit_proposal(session, proposal.id)
    add_review(session, proposal.id, first_item.id, reviewer.id, "accept", "Reviewed")
    add_review(session, proposal.id, second_item.id, reviewer.id, "accept", "Reviewed")
    with pytest.raises(DomainError, match="Claim not found"):
        apply_proposal(session, proposal.id, reviewer.id)
    assert session.query(Claim).count() == 0
