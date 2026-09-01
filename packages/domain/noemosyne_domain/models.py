"""Pure value objects for Noemosyne's Milestone 1 epistemic model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from .errors import DomainError


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class RecordStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"
    REJECTED = "rejected"


class ProposalStatus(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    READY = "ready"
    IN_REVIEW = "in_review"
    ACCEPTED = "accepted"
    PARTIALLY_ACCEPTED = "partially_accepted"
    REJECTED = "rejected"
    STALE = "stale"


class ProposalItemStatus(StrEnum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STALE = "stale"


class ReviewDecisionKind(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
    ABSTAIN = "abstain"


class EvidenceStance(StrEnum):
    SUPPORTS = "supports"
    CHALLENGES = "challenges"
    CONTEXTUALIZES = "contextualizes"


class Verdict(StrEnum):
    UNASSESSED = "unassessed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONTESTED = "contested"
    PROVISIONALLY_SUPPORTED = "provisionally_supported"
    WELL_SUPPORTED = "well_supported"
    PROVISIONALLY_CHALLENGED = "provisionally_challenged"
    WELL_REFUTED = "well_refuted"


class ProfileLevel(StrEnum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Stability(StrEnum):
    FRAGILE = "fragile"
    EVOLVING = "evolving"
    STABLE = "stable"
    UNKNOWN = "unknown"


ALLOWED_RELATIONS = frozenset(
    {
        "equivalent_to",
        "specializes",
        "generalizes",
        "entails",
        "incompatible_with",
        "depends_on",
        "answers",
        "predicts",
        "replicates",
    }
)


@dataclass(frozen=True, slots=True)
class ClaimVersion:
    """Immutable wording and scope for a stable claim identity."""

    claim_id: UUID
    wording: str
    scope: dict[str, Any]
    valid_from: datetime
    recorded_at: datetime = field(default_factory=utc_now)
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.wording.strip():
            raise DomainError("claim.wording_required", "Claim wording cannot be empty")
        if self.valid_from.tzinfo is None or self.recorded_at.tzinfo is None:
            raise DomainError("time.timezone_required", "Domain times must be timezone-aware")


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    """An evaluator's contextual judgment connecting evidence to one claim."""

    claim_id: UUID
    evidence_item_id: UUID
    evaluator_actor_id: UUID
    assessment_policy_id: UUID
    stance: EvidenceStance
    directness: str
    strength_band: str
    scope_match: str
    caveats: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        allowed_directness = {"direct", "indirect", "mechanistic", "analogical", "testimonial"}
        allowed_strength = {"minimal", "limited", "material", "strong", "not_assessed"}
        if self.directness not in allowed_directness:
            raise DomainError("evidence.invalid_directness", "Unknown evidence directness")
        if self.strength_band not in allowed_strength:
            raise DomainError("evidence.invalid_strength", "Unknown evidence strength band")
        if not self.scope_match.strip():
            raise DomainError("evidence.scope_match_required", "Evidence scope match is required")


@dataclass(frozen=True, slots=True)
class AssessmentProfile:
    """Ordinal, multidimensional assessment; deliberately not a truth probability."""

    verdict: Verdict
    directness: ProfileLevel = ProfileLevel.UNKNOWN
    methodological_quality: ProfileLevel = ProfileLevel.UNKNOWN
    independence: ProfileLevel = ProfileLevel.UNKNOWN
    consistency: ProfileLevel = ProfileLevel.UNKNOWN
    scope_fit: ProfileLevel = ProfileLevel.UNKNOWN
    stability: Stability = Stability.UNKNOWN


def validate_assessment_inputs(verdict: Verdict, input_ids: tuple[UUID, ...]) -> None:
    """Require inspectable inputs for every substantive assessment."""
    if verdict is not Verdict.UNASSESSED and not input_ids:
        raise DomainError(
            "assessment.inputs_required",
            "An assessed verdict requires at least one assessment input",
        )


def validate_relation(relation_type: str, context: dict[str, Any]) -> None:
    """Validate the controlled relation vocabulary and contradiction context."""
    if relation_type not in ALLOWED_RELATIONS:
        raise DomainError("relation.not_allowed", f"Relation {relation_type!r} is not canonical")
    if relation_type == "incompatible_with" and not context:
        raise DomainError(
            "relation.context_required",
            "incompatible_with requires an explicit overlap context",
        )


def review_outcome(decisions: tuple[ReviewDecisionKind, ...]) -> ReviewDecisionKind | None:
    """Calculate the conservative effective outcome for one proposal item."""
    substantive = tuple(
        decision for decision in decisions if decision is not ReviewDecisionKind.ABSTAIN
    )
    if ReviewDecisionKind.REQUEST_CHANGES in substantive:
        return ReviewDecisionKind.REQUEST_CHANGES
    if ReviewDecisionKind.REJECT in substantive:
        return ReviewDecisionKind.REJECT
    if ReviewDecisionKind.ACCEPT in substantive:
        return ReviewDecisionKind.ACCEPT
    return None
