from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from noemosyne_db.models import (
    Actor,
    Argument,
    ArgumentPremise,
    AssessmentInput,
    AssessmentPolicy,
    Claim,
    ClaimVersion,
    EpistemicAssessment,
    EvidenceDependencyGroup,
    EvidenceItem,
    EvidenceItemSource,
    EvidenceLink,
    Namespace,
    Proposal,
    ProposalItem,
    SourceArtifact,
    SourceFragment,
)
from noemosyne_db.proposals import add_review, apply_proposal, submit_proposal, validate_proposal
from noemosyne_domain.errors import DomainError


def _accepted_state(session):
    namespace_a = Namespace(slug="namespace-a", name="Namespace A")
    namespace_b = Namespace(slug="namespace-b", name="Namespace B")
    session.add_all([namespace_a, namespace_b])
    session.flush()
    proposer = Actor(
        namespace_id=namespace_a.id, kind="human", display_name="A proposer", external_id="a-p"
    )
    reviewer = Actor(
        namespace_id=namespace_a.id, kind="human", display_name="A reviewer", external_id="a-r"
    )
    actor_b = Actor(
        namespace_id=namespace_b.id, kind="human", display_name="B actor", external_id="b"
    )
    session.add_all([proposer, reviewer, actor_b])
    session.flush()
    policy_b = AssessmentPolicy(
        namespace_id=namespace_b.id,
        name="B policy",
        version="1",
        status="accepted",
    )
    session.add(policy_b)
    session.flush()
    claim_b_id = str(uuid4())
    version_b_id = str(uuid4())
    version_b = ClaimVersion(
        id=version_b_id,
        claim_id=claim_b_id,
        version_number=1,
        wording="Namespace B claim",
        scope_json={},
        valid_from=datetime(2025, 1, 1, tzinfo=UTC),
        status="accepted",
    )
    claim_b = Claim(
        id=claim_b_id,
        namespace_id=namespace_b.id,
        current_version_id=version_b_id,
        status="accepted",
    )
    source_b = SourceArtifact(
        namespace_id=namespace_b.id,
        kind="paper",
        title="B source",
        canonical_uri="https://example.test/b",
        license_basis="metadata-only",
        status="accepted",
    )
    session.add_all([claim_b, version_b, source_b])
    session.flush()
    fragment_b = SourceFragment(
        source_artifact_id=source_b.id,
        locator_json={"section": "results"},
        license_basis="locator-only",
        status="accepted",
    )
    argument_b = Argument(
        namespace_id=namespace_b.id,
        conclusion_claim_id=claim_b.id,
        author_actor_id=actor_b.id,
        inference_scheme="deductive",
        rationale="B reasoning",
        status="accepted",
    )
    group_b = EvidenceDependencyGroup(
        namespace_id=namespace_b.id,
        label="B group",
        dependency_type="study",
        status="accepted",
    )
    session.add_all([fragment_b, argument_b, group_b])
    session.flush()
    premise_b = ArgumentPremise(
        argument_id=argument_b.id,
        premise_type="claim",
        premise_id=claim_b.id,
        position=0,
        status="accepted",
    )
    evidence_b = EvidenceItem(
        namespace_id=namespace_b.id,
        kind="source_fragment",
        status="accepted",
    )
    session.add_all([premise_b, evidence_b])
    session.flush()
    session.add(
        EvidenceItemSource(
            evidence_item_id=evidence_b.id,
            source_fragment_id=fragment_b.id,
            status="accepted",
        )
    )
    link_b = EvidenceLink(
        claim_id=claim_b.id,
        evidence_item_id=evidence_b.id,
        evaluator_actor_id=actor_b.id,
        assessment_policy_id=policy_b.id,
        stance="supports",
        directness="direct",
        strength_band="material",
        scope_match="B scope",
        status="accepted",
    )
    session.add(link_b)
    session.flush()
    assessment_b = EpistemicAssessment(
        claim_id=claim_b.id,
        assessor_actor_id=actor_b.id,
        policy_id=policy_b.id,
        verdict="provisionally_supported",
        rationale="B assessment",
        valid_from=datetime(2025, 1, 1, tzinfo=UTC),
        status="accepted",
    )
    session.add(assessment_b)
    session.flush()
    session.add(
        AssessmentInput(
            assessment_id=assessment_b.id,
            input_type="evidence_link",
            input_id=link_b.id,
            position=0,
            status="accepted",
        )
    )
    session.commit()
    return {
        "a": namespace_a,
        "b": namespace_b,
        "proposer": proposer,
        "reviewer": reviewer,
        "actor_b": actor_b,
        "claim_b": claim_b,
        "source_b": source_b,
        "fragment_b": fragment_b,
        "evidence_b": evidence_b,
        "group_b": group_b,
        "policy_b": policy_b,
        "link_b": link_b,
        "assessment_b": assessment_b,
    }


def _proposal_with_item(session, state, command_type: str, payload: dict[str, object]):
    proposal = Proposal(
        namespace_id=state["a"].id,
        proposer_actor_id=state["proposer"].id,
        title=f"Cross namespace {command_type}",
        base_revision_token=0,
    )
    session.add(proposal)
    session.flush()
    item = ProposalItem(
        proposal_id=proposal.id,
        position=0,
        command_type=command_type,
        payload_json=payload,
    )
    session.add(item)
    session.commit()
    return proposal, item


def test_every_cross_namespace_reference_path_is_rejected_without_token_change(session) -> None:
    state = _accepted_state(session)
    timestamp = datetime(2025, 2, 1, tzinfo=UTC).isoformat()
    cases = [
        (
            "AddClaimVersion",
            {
                "claim_id": state["claim_b"].id,
                "wording": "Attempted B rewrite",
                "scope_json": {},
                "valid_from": timestamp,
            },
        ),
        (
            "AddSourceFragment",
            {
                "source_artifact_id": state["source_b"].id,
                "locator_json": {"section": "x"},
                "license_basis": "locator-only",
            },
        ),
        (
            "CreateEvidenceItem",
            {"kind": "source_fragment", "source_fragment_ids": [state["fragment_b"].id]},
        ),
        (
            "AddEvidenceDependencyMember",
            {
                "dependency_group_id": state["group_b"].id,
                "evidence_item_id": state["evidence_b"].id,
            },
        ),
        (
            "LinkEvidenceToClaim",
            {
                "claim_id": state["claim_b"].id,
                "evidence_item_id": state["evidence_b"].id,
                "evaluator_actor_id": state["actor_b"].id,
                "assessment_policy_id": state["policy_b"].id,
                "stance": "supports",
                "directness": "direct",
                "strength_band": "material",
                "scope_match": "cross namespace",
            },
        ),
        (
            "RelateClaims",
            {
                "source_claim_id": state["claim_b"].id,
                "target_claim_id": state["claim_b"].id,
                "relation_type": "depends_on",
                "context_json": {},
            },
        ),
        (
            "AddAssertion",
            {
                "claim_id": state["claim_b"].id,
                "actor_id": state["actor_b"].id,
                "stance": "asserts",
                "asserted_at": timestamp,
            },
        ),
        (
            "CreateAssessment",
            {
                "claim_id": state["claim_b"].id,
                "assessor_actor_id": state["actor_b"].id,
                "policy_id": state["policy_b"].id,
                "verdict": "provisionally_supported",
                "rationale": "cross namespace",
                "input_ids": [state["link_b"].id],
                "valid_from": timestamp,
            },
        ),
        (
            "CreateRevisionEvent",
            {
                "claim_id": state["claim_b"].id,
                "before_assessment_id": None,
                "after_assessment_id": state["assessment_b"].id,
                "rationale": "cross namespace",
            },
        ),
    ]
    for command_type, payload in cases:
        proposal, item = _proposal_with_item(session, state, command_type, payload)
        validate_proposal(session, proposal.id)
        session.refresh(item)
        assert item.status == "invalid"
        assert item.validation_errors_json[0]["code"] == "reference.namespace_mismatch"
    assert state["a"].revision_token == 0
    assert state["b"].revision_token == 0


def test_apply_revalidates_references_inside_transaction(session) -> None:
    state = _accepted_state(session)
    claim_a_id = "20000000-0000-0000-0000-000000000001"
    proposal, item = _proposal_with_item(
        session,
        state,
        "CreateClaim",
        {
            "id": claim_a_id,
            "wording": "Namespace A claim",
            "scope_json": {},
            "valid_from": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
        },
    )
    validate_proposal(session, proposal.id)
    submit_proposal(session, proposal.id)
    add_review(session, proposal.id, item.id, state["reviewer"].id, "accept", "Reviewed")
    item.command_type = "AddClaimVersion"
    item.payload_json = {
        "claim_id": state["claim_b"].id,
        "wording": "Transactionally rejected B rewrite",
        "scope_json": {},
        "valid_from": datetime(2025, 3, 1, tzinfo=UTC).isoformat(),
    }
    session.commit()

    with pytest.raises(DomainError) as raised:
        apply_proposal(session, proposal.id, state["reviewer"].id)
    assert raised.value.code == "reference.namespace_mismatch"
    assert state["a"].revision_token == 0
    assert state["b"].revision_token == 0
    assert session.get(Claim, claim_a_id) is None


def test_reviewer_and_applier_must_belong_to_proposal_namespace(session) -> None:
    state = _accepted_state(session)
    proposal, item = _proposal_with_item(
        session,
        state,
        "CreateClaim",
        {
            "wording": "Namespace A candidate",
            "scope_json": {},
            "valid_from": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
        },
    )
    validate_proposal(session, proposal.id)
    submit_proposal(session, proposal.id)
    with pytest.raises(DomainError) as reviewer_error:
        add_review(session, proposal.id, item.id, state["actor_b"].id, "accept", "Invalid")
    assert reviewer_error.value.code == "review.reviewer_namespace_mismatch"
    add_review(session, proposal.id, item.id, state["reviewer"].id, "accept", "Valid review")
    with pytest.raises(DomainError) as applier_error:
        apply_proposal(session, proposal.id, state["actor_b"].id)
    assert applier_error.value.code == "proposal.applier_namespace_mismatch"
    assert state["a"].revision_token == 0
    assert state["b"].revision_token == 0
