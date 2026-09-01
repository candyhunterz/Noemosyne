"""SQLAlchemy mappings for all Milestone 1 tables.

String-backed vocabularies plus check constraints keep vocabulary migrations portable.
Accepted records are protected by PostgreSQL triggers installed by Alembic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


def now_utc() -> datetime:
    return datetime.now(UTC)


RECORD_CHECK = "status IN ('proposed','accepted','superseded','withdrawn','rejected')"


class Base(DeclarativeBase):
    """Declarative model base."""


class IdTimeMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, index=True
    )


class CanonicalMixin(IdTimeMixin):
    status: Mapped[str] = mapped_column(String(24), default="accepted")
    supersedes_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    proposal_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("proposal_items.id"), nullable=True, index=True
    )


class Namespace(Base, IdTimeMixin):
    __tablename__ = "namespaces"
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(240))
    revision_token: Mapped[int] = mapped_column(BigInteger, default=0)


class Actor(Base, IdTimeMixin):
    __tablename__ = "actors"
    namespace_id: Mapped[str] = mapped_column(ForeignKey("namespaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(240))
    external_id: Mapped[str | None] = mapped_column(String(240))
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("namespace_id", "kind", "external_id"),)


class Entity(Base, CanonicalMixin):
    __tablename__ = "entities"
    namespace_id: Mapped[str] = mapped_column(ForeignKey("namespaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(80))
    canonical_name: Mapped[str] = mapped_column(String(400))
    external_ids_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (CheckConstraint(RECORD_CHECK, name="ck_entities_status"),)


class EntityAlias(Base, CanonicalMixin):
    __tablename__ = "entity_aliases"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    alias: Mapped[str] = mapped_column(String(400))
    __table_args__ = (
        CheckConstraint(RECORD_CHECK, name="ck_entity_aliases_status"),
        UniqueConstraint("entity_id", "alias"),
    )


class Claim(Base, CanonicalMixin):
    __tablename__ = "claims"
    namespace_id: Mapped[str] = mapped_column(ForeignKey("namespaces.id"), index=True)
    current_version_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "claim_versions.id",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
            name="fk_claims_current_version",
        ),
        nullable=True,
        index=True,
    )
    claim_form: Mapped[str] = mapped_column(String(80), default="proposition")
    normalization_status: Mapped[str] = mapped_column(String(40), default="canonical")
    __table_args__ = (CheckConstraint(RECORD_CHECK, name="ck_claims_status"),)


class ClaimVersion(Base, CanonicalMixin):
    __tablename__ = "claim_versions"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    wording: Mapped[str] = mapped_column(Text)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        CheckConstraint(RECORD_CHECK, name="ck_claim_versions_status"),
        CheckConstraint("length(trim(wording)) > 0", name="ck_claim_versions_wording"),
        UniqueConstraint("claim_id", "version_number"),
    )


class ClaimEntity(Base, CanonicalMixin):
    __tablename__ = "claim_entities"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    role: Mapped[str] = mapped_column(String(80))
    __table_args__ = (CheckConstraint(RECORD_CHECK, name="ck_claim_entities_status"),)


class SourceArtifact(Base, CanonicalMixin):
    __tablename__ = "source_artifacts"
    namespace_id: Mapped[str] = mapped_column(ForeignKey("namespaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(Text)
    canonical_uri: Mapped[str] = mapped_column(Text)
    authors_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128))
    license_basis: Mapped[str] = mapped_column(String(240))
    access_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (
        CheckConstraint(RECORD_CHECK, name="ck_source_artifacts_status"),
        UniqueConstraint("namespace_id", "canonical_uri", "content_hash"),
    )


class SourceFragment(Base, CanonicalMixin):
    __tablename__ = "source_fragments"
    source_artifact_id: Mapped[str] = mapped_column(ForeignKey("source_artifacts.id"), index=True)
    locator_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    stored_text: Mapped[str | None] = mapped_column(Text)
    text_hash: Mapped[str | None] = mapped_column(String(128))
    license_basis: Mapped[str] = mapped_column(String(240))
    __table_args__ = (
        CheckConstraint(RECORD_CHECK, name="ck_source_fragments_status"),
        CheckConstraint("stored_text IS NULL OR text_hash IS NOT NULL", name="ck_fragment_hash"),
    )


class Assertion(Base, CanonicalMixin):
    __tablename__ = "assertions"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"), index=True)
    source_fragment_id: Mapped[str | None] = mapped_column(ForeignKey("source_fragments.id"))
    stance: Mapped[str] = mapped_column(String(24))
    asserted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(RECORD_CHECK, name="ck_assertions_status"),
        CheckConstraint(
            "stance IN ('asserts','denies','questions','withholds')", name="ck_assertion_stance"
        ),
    )


class Argument(Base, CanonicalMixin):
    __tablename__ = "arguments"
    namespace_id: Mapped[str] = mapped_column(ForeignKey("namespaces.id"), index=True)
    conclusion_claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    author_actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    inference_scheme: Mapped[str] = mapped_column(String(80))
    rationale: Mapped[str] = mapped_column(Text)
    assumptions_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    defeaters_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    __table_args__ = (CheckConstraint(RECORD_CHECK, name="ck_arguments_status"),)


class ArgumentPremise(Base, CanonicalMixin):
    __tablename__ = "argument_premises"
    argument_id: Mapped[str] = mapped_column(ForeignKey("arguments.id"), index=True)
    premise_type: Mapped[str] = mapped_column(String(40))
    premise_id: Mapped[str] = mapped_column(String(36), index=True)
    position: Mapped[int] = mapped_column(Integer)
    __table_args__ = (CheckConstraint(RECORD_CHECK, name="ck_argument_premises_status"),)


class EvidenceItem(Base, CanonicalMixin):
    __tablename__ = "evidence_items"
    namespace_id: Mapped[str] = mapped_column(ForeignKey("namespaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    argument_id: Mapped[str | None] = mapped_column(ForeignKey("arguments.id"))
    description: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (
        CheckConstraint(RECORD_CHECK, name="ck_evidence_items_status"),
        CheckConstraint("kind IN ('source_fragment','argument')", name="ck_evidence_item_kind"),
    )


class EvidenceItemSource(Base, CanonicalMixin):
    __tablename__ = "evidence_item_sources"
    evidence_item_id: Mapped[str] = mapped_column(ForeignKey("evidence_items.id"), index=True)
    source_fragment_id: Mapped[str] = mapped_column(ForeignKey("source_fragments.id"), index=True)
    __table_args__ = (
        CheckConstraint(RECORD_CHECK, name="ck_evidence_item_sources_status"),
        UniqueConstraint("evidence_item_id", "source_fragment_id"),
    )


class EvidenceDependencyGroup(Base, CanonicalMixin):
    __tablename__ = "evidence_dependency_groups"
    namespace_id: Mapped[str] = mapped_column(ForeignKey("namespaces.id"), index=True)
    label: Mapped[str] = mapped_column(String(400))
    dependency_type: Mapped[str] = mapped_column(String(80))
    rationale: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (CheckConstraint(RECORD_CHECK, name="ck_dependency_groups_status"),)


class EvidenceDependencyMember(Base, CanonicalMixin):
    __tablename__ = "evidence_dependency_members"
    dependency_group_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_dependency_groups.id"), index=True
    )
    evidence_item_id: Mapped[str] = mapped_column(ForeignKey("evidence_items.id"), index=True)
    __table_args__ = (
        CheckConstraint(RECORD_CHECK, name="ck_dependency_members_status"),
        UniqueConstraint("dependency_group_id", "evidence_item_id"),
    )


class AssessmentPolicy(Base, CanonicalMixin):
    __tablename__ = "assessment_policies"
    namespace_id: Mapped[str] = mapped_column(ForeignKey("namespaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    version: Mapped[str] = mapped_column(String(80))
    rules_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (
        CheckConstraint(RECORD_CHECK, name="ck_assessment_policies_status"),
        UniqueConstraint("namespace_id", "name", "version"),
    )


class EvidenceLink(Base, CanonicalMixin):
    __tablename__ = "evidence_links"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    evidence_item_id: Mapped[str] = mapped_column(ForeignKey("evidence_items.id"), index=True)
    evaluator_actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    assessment_policy_id: Mapped[str] = mapped_column(ForeignKey("assessment_policies.id"))
    dependency_group_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_dependency_groups.id")
    )
    stance: Mapped[str] = mapped_column(String(24))
    directness: Mapped[str] = mapped_column(String(24))
    strength_band: Mapped[str] = mapped_column(String(24))
    scope_match: Mapped[str] = mapped_column(Text)
    caveats_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(RECORD_CHECK, name="ck_evidence_links_status"),
        CheckConstraint(
            "stance IN ('supports','challenges','contextualizes')", name="ck_evidence_stance"
        ),
        CheckConstraint(
            "directness IN ('direct','indirect','mechanistic','analogical','testimonial')",
            name="ck_evidence_directness",
        ),
        CheckConstraint(
            "strength_band IN ('minimal','limited','material','strong','not_assessed')",
            name="ck_evidence_strength",
        ),
        CheckConstraint("length(trim(scope_match)) > 0", name="ck_evidence_scope_match"),
    )


class Challenge(Base, CanonicalMixin):
    __tablename__ = "challenges"
    namespace_id: Mapped[str] = mapped_column(ForeignKey("namespaces.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    category: Mapped[str] = mapped_column(String(80))
    explanation: Mapped[str] = mapped_column(Text)
    raised_by_actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    resolution_status: Mapped[str] = mapped_column(String(40), default="open")
    resolution: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint(RECORD_CHECK, name="ck_challenges_status"),)


class ClaimRelation(Base, CanonicalMixin):
    __tablename__ = "claim_relations"
    source_claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    target_claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    relation_type: Mapped[str] = mapped_column(String(40))
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reviewer_actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    __table_args__ = (
        CheckConstraint(RECORD_CHECK, name="ck_claim_relations_status"),
        CheckConstraint(
            "relation_type IN ('equivalent_to','specializes','generalizes','entails',"
            "'incompatible_with','depends_on','answers','predicts','replicates')",
            name="ck_relation_type",
        ),
    )


class EpistemicAssessment(Base, CanonicalMixin):
    __tablename__ = "epistemic_assessments"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    assessor_actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    policy_id: Mapped[str] = mapped_column(ForeignKey("assessment_policies.id"))
    verdict: Mapped[str] = mapped_column(String(40))
    directness: Mapped[str] = mapped_column(String(16), default="unknown")
    methodological_quality: Mapped[str] = mapped_column(String(16), default="unknown")
    independence: Mapped[str] = mapped_column(String(16), default="unknown")
    consistency: Mapped[str] = mapped_column(String(16), default="unknown")
    scope_fit: Mapped[str] = mapped_column(String(16), default="unknown")
    stability: Mapped[str] = mapped_column(String(16), default="unknown")
    rationale: Mapped[str] = mapped_column(Text)
    uncertainty_drivers_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(RECORD_CHECK, name="ck_assessments_status"),
        CheckConstraint(
            "verdict IN ('unassessed','insufficient_evidence','contested',"
            "'provisionally_supported','well_supported','provisionally_challenged',"
            "'well_refuted')",
            name="ck_assessment_verdict",
        ),
        CheckConstraint(
            "directness IN ('unknown','low','medium','high') AND "
            "methodological_quality IN ('unknown','low','medium','high') AND "
            "independence IN ('unknown','low','medium','high') AND "
            "consistency IN ('unknown','low','medium','high') AND "
            "scope_fit IN ('unknown','low','medium','high')",
            name="ck_assessment_profile_levels",
        ),
        CheckConstraint(
            "stability IN ('fragile','evolving','stable','unknown')",
            name="ck_assessment_stability",
        ),
    )


class AssessmentInput(Base, CanonicalMixin):
    __tablename__ = "assessment_inputs"
    assessment_id: Mapped[str] = mapped_column(ForeignKey("epistemic_assessments.id"), index=True)
    input_type: Mapped[str] = mapped_column(String(40))
    input_id: Mapped[str] = mapped_column(String(36), index=True)
    position: Mapped[int] = mapped_column(Integer)
    __table_args__ = (CheckConstraint(RECORD_CHECK, name="ck_assessment_inputs_status"),)


class RevisionEvent(Base, CanonicalMixin):
    __tablename__ = "revision_events"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    before_assessment_id: Mapped[str | None] = mapped_column(ForeignKey("epistemic_assessments.id"))
    after_assessment_id: Mapped[str] = mapped_column(ForeignKey("epistemic_assessments.id"))
    author_actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    reviewer_actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    rationale: Mapped[str] = mapped_column(Text)
    triggering_inputs_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (CheckConstraint(RECORD_CHECK, name="ck_revision_events_status"),)


class RevisionImpact(Base, CanonicalMixin):
    __tablename__ = "revision_impacts"
    revision_event_id: Mapped[str] = mapped_column(ForeignKey("revision_events.id"), index=True)
    affected_type: Mapped[str] = mapped_column(String(40))
    affected_id: Mapped[str] = mapped_column(String(36), index=True)
    description: Mapped[str] = mapped_column(Text)
    __table_args__ = (CheckConstraint(RECORD_CHECK, name="ck_revision_impacts_status"),)


class Question(Base, CanonicalMixin):
    __tablename__ = "questions"
    namespace_id: Mapped[str] = mapped_column(ForeignKey("namespaces.id"), index=True)
    wording: Mapped[str] = mapped_column(Text)
    importance_rationale: Mapped[str] = mapped_column(Text)
    tractability: Mapped[str] = mapped_column(String(40), default="unknown")
    __table_args__ = (CheckConstraint(RECORD_CHECK, name="ck_questions_status"),)


class QuestionClaim(Base, CanonicalMixin):
    __tablename__ = "question_claims"
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), index=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    role: Mapped[str] = mapped_column(String(40), default="candidate_answer")
    __table_args__ = (CheckConstraint(RECORD_CHECK, name="ck_question_claims_status"),)


class Proposal(Base, IdTimeMixin):
    __tablename__ = "proposals"
    namespace_id: Mapped[str] = mapped_column(ForeignKey("namespaces.id"), index=True)
    proposer_actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    title: Mapped[str] = mapped_column(String(400))
    description: Mapped[str] = mapped_column(Text, default="")
    base_revision_token: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_by_actor_id: Mapped[str | None] = mapped_column(ForeignKey("actors.id"))
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','validating','ready','in_review','accepted',"
            "'partially_accepted','rejected','stale')",
            name="ck_proposal_status",
        ),
    )


class ProposalItem(Base, IdTimeMixin):
    __tablename__ = "proposal_items"
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    command_type: Mapped[str] = mapped_column(String(100))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    preconditions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    validation_errors_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_canonical_ids_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','valid','invalid','accepted','rejected','stale')",
            name="ck_proposal_item_status",
        ),
        UniqueConstraint("proposal_id", "position"),
    )


class ReviewDecision(Base, IdTimeMixin):
    __tablename__ = "review_decisions"
    proposal_item_id: Mapped[str] = mapped_column(ForeignKey("proposal_items.id"), index=True)
    reviewer_actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"), index=True)
    decision: Mapped[str] = mapped_column(String(24))
    rationale: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(
            "decision IN ('accept','reject','request_changes','abstain')", name="ck_review_decision"
        ),
    )


class AuditEvent(Base, IdTimeMixin):
    __tablename__ = "audit_events"
    namespace_id: Mapped[str] = mapped_column(ForeignKey("namespaces.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    object_type: Mapped[str] = mapped_column(String(100))
    object_id: Mapped[str] = mapped_column(String(240), index=True)
    proposal_id: Mapped[str | None] = mapped_column(ForeignKey("proposals.id"))
    detail_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Job(Base, IdTimeMixin):
    __tablename__ = "jobs"
    namespace_id: Mapped[str] = mapped_column(ForeignKey("namespaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index(
    "ix_claim_versions_history",
    ClaimVersion.claim_id,
    ClaimVersion.recorded_at,
    ClaimVersion.valid_from,
)
Index(
    "ix_assessments_history",
    EpistemicAssessment.claim_id,
    EpistemicAssessment.recorded_at,
    EpistemicAssessment.valid_from,
)
Index("ix_relations_trace", ClaimRelation.source_claim_id, ClaimRelation.relation_type)
