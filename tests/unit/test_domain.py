from datetime import UTC, datetime
from uuid import uuid4

import pytest
from noemosyne_domain.errors import DomainError
from noemosyne_domain.models import (
    AssessmentProfile,
    ClaimVersion,
    EvidenceLink,
    EvidenceStance,
    ReviewDecisionKind,
    Verdict,
    review_outcome,
    validate_assessment_inputs,
    validate_relation,
)


def test_claim_version_requires_wording_and_aware_time() -> None:
    with pytest.raises(DomainError, match="wording"):
        ClaimVersion(uuid4(), " ", {}, datetime.now(UTC))
    with pytest.raises(DomainError, match="timezone"):
        ClaimVersion(uuid4(), "Claim", {}, datetime.now())


def test_evidence_link_requires_contextual_judgment() -> None:
    with pytest.raises(DomainError, match="scope match"):
        EvidenceLink(
            claim_id=uuid4(),
            evidence_item_id=uuid4(),
            evaluator_actor_id=uuid4(),
            assessment_policy_id=uuid4(),
            stance=EvidenceStance.SUPPORTS,
            directness="direct",
            strength_band="material",
            scope_match="",
        )


def test_incompatible_claims_require_overlap_context() -> None:
    with pytest.raises(DomainError, match="overlap context"):
        validate_relation("incompatible_with", {})
    validate_relation("incompatible_with", {"task": "same benchmark version"})


def test_assessment_is_ordinal_and_requires_inputs() -> None:
    profile = AssessmentProfile(Verdict.PROVISIONALLY_SUPPORTED)
    assert not hasattr(profile, "confidence")
    with pytest.raises(DomainError, match="input"):
        validate_assessment_inputs(profile.verdict, ())
    validate_assessment_inputs(Verdict.UNASSESSED, ())


def test_review_outcome_is_conservative() -> None:
    assert review_outcome((ReviewDecisionKind.ACCEPT,)) is ReviewDecisionKind.ACCEPT
    assert (
        review_outcome((ReviewDecisionKind.ACCEPT, ReviewDecisionKind.REJECT))
        is ReviewDecisionKind.REJECT
    )
    assert review_outcome((ReviewDecisionKind.ABSTAIN,)) is None
