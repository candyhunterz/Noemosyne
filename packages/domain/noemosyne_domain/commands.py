"""Typed commands accepted by application services and proposal payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from .models import AssessmentProfile, EvidenceStance, ReviewDecisionKind


@dataclass(frozen=True, slots=True)
class RegisterSourceArtifact:
    namespace_id: UUID
    title: str
    kind: str
    canonical_uri: str
    license_basis: str
    access_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AddSourceFragment:
    source_artifact_id: UUID
    locator_json: dict[str, Any]
    license_basis: str
    stored_text: str | None = None
    text_hash: str | None = None


@dataclass(frozen=True, slots=True)
class CreateClaim:
    namespace_id: UUID
    wording: str
    scope_json: dict[str, Any]
    valid_from: datetime


@dataclass(frozen=True, slots=True)
class AddClaimVersion:
    claim_id: UUID
    wording: str
    scope_json: dict[str, Any]
    valid_from: datetime


@dataclass(frozen=True, slots=True)
class AddAssertion:
    claim_id: UUID
    actor_id: UUID
    stance: str
    source_fragment_id: UUID | None
    asserted_at: datetime


@dataclass(frozen=True, slots=True)
class CreateEvidenceItem:
    namespace_id: UUID
    kind: str
    source_fragment_ids: tuple[UUID, ...] = ()
    argument_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class LinkEvidenceToClaim:
    claim_id: UUID
    evidence_item_id: UUID
    evaluator_actor_id: UUID
    assessment_policy_id: UUID
    stance: EvidenceStance
    directness: str
    strength_band: str
    scope_match: str
    caveats: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CreateEvidenceDependencyGroup:
    namespace_id: UUID
    label: str
    dependency_type: str


@dataclass(frozen=True, slots=True)
class AddEvidenceDependencyMember:
    dependency_group_id: UUID
    evidence_item_id: UUID


@dataclass(frozen=True, slots=True)
class RelateClaims:
    source_claim_id: UUID
    target_claim_id: UUID
    relation_type: str
    context_json: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CreateArgument:
    namespace_id: UUID
    conclusion_claim_id: UUID
    author_actor_id: UUID
    inference_scheme: str
    premise_ids: tuple[UUID, ...]
    rationale: str


@dataclass(frozen=True, slots=True)
class RaiseChallenge:
    namespace_id: UUID
    target_type: str
    target_id: UUID
    category: str
    explanation: str
    raised_by_actor_id: UUID


@dataclass(frozen=True, slots=True)
class CreateAssessment:
    claim_id: UUID
    assessor_actor_id: UUID
    policy_id: UUID
    profile: AssessmentProfile
    rationale: str
    uncertainty_drivers: tuple[str, ...]
    input_ids: tuple[UUID, ...]
    valid_from: datetime


@dataclass(frozen=True, slots=True)
class CreateRevisionEvent:
    claim_id: UUID
    before_assessment_id: UUID | None
    after_assessment_id: UUID
    rationale: str


@dataclass(frozen=True, slots=True)
class CreateQuestion:
    namespace_id: UUID
    wording: str
    importance_rationale: str


@dataclass(frozen=True, slots=True)
class CreateProposal:
    namespace_id: UUID
    proposer_actor_id: UUID
    title: str
    base_revision_token: int


@dataclass(frozen=True, slots=True)
class AddProposalItem:
    proposal_id: UUID
    command_type: str
    payload: dict[str, Any]
    preconditions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SubmitProposal:
    proposal_id: UUID


@dataclass(frozen=True, slots=True)
class RecordReviewDecision:
    proposal_item_id: UUID
    reviewer_actor_id: UUID
    decision: ReviewDecisionKind
    rationale: str


@dataclass(frozen=True, slots=True)
class ApplyAcceptedProposal:
    proposal_id: UUID
    applied_by_actor_id: UUID
