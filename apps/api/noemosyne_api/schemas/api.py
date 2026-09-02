"""Versioned public request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

JsonObject = dict[str, JsonValue]
MutationCommandType = Literal[
    "CreateClaim",
    "AddClaimVersion",
    "RegisterSourceArtifact",
    "AddSourceFragment",
    "CreateEvidenceItem",
    "CreateEvidenceDependencyGroup",
    "AddEvidenceDependencyMember",
    "LinkEvidenceToClaim",
    "RelateClaims",
    "AddAssertion",
    "CreateArgument",
    "RaiseChallenge",
    "CreateAssessment",
    "CreateRevisionEvent",
    "CreateQuestion",
]
ProposalCommandType = MutationCommandType | Literal["ImportSeedPackage"]
ReviewKind = Literal["accept", "reject", "request_changes", "abstain"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposalCreate(ApiModel):
    namespace_id: str
    proposer_actor_id: str
    title: str = Field(min_length=1, max_length=400)
    description: str = ""
    base_revision_token: int = Field(ge=0)


class ProposalItemCreate(ApiModel):
    command_type: MutationCommandType
    payload: JsonObject
    preconditions: JsonObject = Field(default_factory=dict)


class ReviewCreate(ApiModel):
    proposal_item_id: str
    reviewer_actor_id: str
    decision: ReviewKind
    rationale: str = Field(min_length=1)


class ApplyRequest(ApiModel):
    applied_by_actor_id: str


class SearchRequest(ApiModel):
    namespace_id: str
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=20, ge=1, le=100)
    verdicts: list[str] = Field(default_factory=list)


class GraphTraceRequest(ApiModel):
    start_claim_id: str
    relation_types: set[str]
    max_depth: int = Field(default=3, ge=0, le=3)
    max_nodes: int = Field(default=100, ge=1, le=100)


class HealthResponse(ApiModel):
    status: Literal["ok", "ready"]


class NamespaceResponse(ApiModel):
    id: str
    slug: str
    name: str
    revision_token: int
    recorded_at: datetime


class ActorResponse(ApiModel):
    id: str
    namespace_id: str
    kind: str
    display_name: str
    external_id: str | None
    provenance: JsonObject
    recorded_at: datetime


class ActorListResponse(ApiModel):
    actors: list[ActorResponse]


class ClaimVersionResponse(ApiModel):
    id: str
    version_number: int
    wording: str
    scope: JsonObject
    valid_from: datetime
    recorded_at: datetime
    supersedes_id: str | None = None


class ClaimResponse(ApiModel):
    id: str
    namespace_id: str
    claim_form: str
    status: str
    current_version: ClaimVersionResponse


class ContextClaimResponse(ApiModel):
    id: str
    version_id: str
    wording: str
    scope: JsonObject
    valid_from: datetime
    recorded_at: datetime


class AssessmentProfileResponse(ApiModel):
    directness: str
    methodological_quality: str
    independence: str
    consistency: str
    scope_fit: str
    stability: str


class PolicyResponse(ApiModel):
    id: str
    name: str
    version: str


class AssessmentResponse(ApiModel):
    id: str
    verdict: str
    profile: AssessmentProfileResponse
    rationale: str
    uncertainty_drivers: list[JsonValue]
    assessor_actor_id: str
    policy: PolicyResponse | None
    input_ids: list[str]
    recorded_at: datetime


class DependencyGroupResponse(ApiModel):
    id: str
    label: str
    dependency_type: str


class SourceProvenanceResponse(ApiModel):
    source_id: str
    title: str
    uri: str
    license_basis: str
    fragment_id: str
    locator: JsonObject


class ArgumentPremiseResponse(ApiModel):
    type: str
    id: str
    position: int


class ArgumentProvenanceResponse(ApiModel):
    id: str
    conclusion_claim_id: str
    author_actor_id: str
    inference_scheme: str
    rationale: str
    premises: list[ArgumentPremiseResponse]


class ContextEvidenceItemResponse(ApiModel):
    evidence_link_id: str
    evidence_item_id: str
    stance: str
    directness: str
    strength_band: str
    scope_match: str
    caveats: list[JsonValue]
    evaluator_actor_id: str
    assessment_policy_id: str
    argument: ArgumentProvenanceResponse | None
    sources: list[SourceProvenanceResponse]


class EvidenceGroupResponse(ApiModel):
    dependency_group: DependencyGroupResponse | None
    items: list[ContextEvidenceItemResponse]


class ChallengeResponse(ApiModel):
    id: str
    category: str
    explanation: str
    raised_by_actor_id: str


class HistorySummaryResponse(ApiModel):
    assessment_count: int
    verdict_sequence: list[str]


class ContextQueryResponse(ApiModel):
    knowledge_cutoff: datetime
    domain_time: datetime


class ContextBundleResponse(ApiModel):
    claim: ContextClaimResponse | None
    assessment: AssessmentResponse | None
    evidence_groups: list[EvidenceGroupResponse]
    open_challenges: list[ChallengeResponse]
    history_summary: HistorySummaryResponse | None
    query: ContextQueryResponse
    omissions: dict[str, int]


class AssessmentTimelineResponse(ApiModel):
    id: str
    verdict: str
    rationale: str
    recorded_at: datetime
    valid_from: datetime
    supersedes_id: str | None


class RevisionResponse(ApiModel):
    id: str
    before_assessment_id: str | None
    after_assessment_id: str
    rationale: str
    recorded_at: datetime


class HistoryComparisonResponse(ApiModel):
    from_: AssessmentTimelineResponse = Field(alias="from", serialization_alias="from")
    to: AssessmentTimelineResponse


class ClaimHistoryResponse(ApiModel):
    claim_id: str
    timeline: list[AssessmentTimelineResponse]
    revisions: list[RevisionResponse]
    comparison: HistoryComparisonResponse | None


class SearchScoresResponse(ApiModel):
    substring: float
    lexical: float | None
    semantic: float | None


class SearchResultResponse(ApiModel):
    claim_id: str
    wording: str
    scope: JsonObject
    scores: SearchScoresResponse


class SearchResponse(ApiModel):
    query: str
    results: list[SearchResultResponse]


class GraphEdgeResponse(ApiModel):
    id: str
    source: str
    target: str
    type: str
    depth: int


class GraphTraceResponse(ApiModel):
    nodes: list[str]
    edges: list[GraphEdgeResponse]
    truncated: bool


class SourceFragmentResponse(ApiModel):
    id: str
    locator: JsonObject
    text_hash: str | None
    license_basis: str


class SourceResponse(ApiModel):
    id: str
    kind: str
    title: str
    canonical_uri: str
    authors: list[JsonValue]
    license_basis: str
    access: JsonObject
    fragments: list[SourceFragmentResponse]


class ActivityEventResponse(ApiModel):
    id: str
    event_type: str
    object_type: str
    object_id: str
    actor_id: str
    proposal_id: str | None
    detail: JsonObject
    recorded_at: datetime


class ActivityResponse(ApiModel):
    events: list[ActivityEventResponse]


class ValidationErrorResponse(ApiModel):
    code: str
    detail: str


class ReviewResponse(ApiModel):
    id: str
    reviewer_actor_id: str
    decision: ReviewKind
    rationale: str
    recorded_at: datetime


class ProposalItemResponse(ApiModel):
    id: str
    position: int
    command_type: ProposalCommandType
    payload: JsonObject
    preconditions: JsonObject
    status: str
    validation_errors: list[ValidationErrorResponse]
    created_canonical_ids: list[str]
    effective_outcome: ReviewKind | None
    reviews: list[ReviewResponse]


class ProposalResponse(ApiModel):
    id: str
    namespace_id: str
    proposer_actor_id: str
    title: str
    description: str
    base_revision_token: int
    status: str
    recorded_at: datetime
    submitted_at: datetime | None
    applied_at: datetime | None
    applied_by_actor_id: str | None
    items: list[ProposalItemResponse]


class ProposalListResponse(ApiModel):
    proposals: list[ProposalResponse]


class ProblemDetail(ApiModel):
    type: str
    title: str
    status: int
    detail: str
    code: str
    instance: str | None = None
