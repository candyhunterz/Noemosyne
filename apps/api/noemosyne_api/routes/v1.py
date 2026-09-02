"""Canonical REST read and proposal workflow routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from noemosyne_db.models import (
    Actor,
    AuditEvent,
    Claim,
    ClaimVersion,
    EpistemicAssessment,
    Namespace,
    Proposal,
    ProposalItem,
    ReviewDecision,
    RevisionEvent,
    SourceArtifact,
    SourceFragment,
)
from noemosyne_db.proposals import (
    add_review,
    apply_proposal,
    effective_review_outcome,
    submit_proposal,
    validate_proposal,
)
from noemosyne_retrieval import build_context_bundle, trace_claim_graph
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from ..dependencies import get_session
from ..schemas import (
    ActivityResponse,
    ActorListResponse,
    ApplyRequest,
    ClaimHistoryResponse,
    ClaimResponse,
    ContextBundleResponse,
    GraphTraceRequest,
    GraphTraceResponse,
    HealthResponse,
    NamespaceResponse,
    ProblemDetail,
    ProposalCreate,
    ProposalItemCreate,
    ProposalListResponse,
    ProposalResponse,
    ReviewCreate,
    SearchRequest,
    SearchResponse,
    SourceResponse,
)

PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": ProblemDetail,
        "description": "Domain invariant violated",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/ProblemDetail"}}
        },
    },
    404: {
        "model": ProblemDetail,
        "description": "Not found",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/ProblemDetail"}}
        },
    },
    409: {
        "model": ProblemDetail,
        "description": "Conflict",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/ProblemDetail"}}
        },
    },
    422: {
        "model": ProblemDetail,
        "description": "Request validation failed",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/ProblemDetail"}}
        },
    },
}
router = APIRouter(prefix="/v1", responses=PROBLEM_RESPONSES)
DbSession = Annotated[Session, Depends(get_session)]


def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove source text from proposal payloads while retaining reviewable metadata."""
    public = dict(payload)
    if "stored_text" in public:
        public.pop("stored_text")
        public["stored_text_present"] = True
    return public


def _utc_datetime(value: datetime | None) -> datetime | None:
    """Normalize SQLite and PostgreSQL timestamps to the same public UTC shape."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _serialize_proposal(session: Session, proposal: Proposal) -> ProposalResponse:
    items = session.scalars(
        select(ProposalItem)
        .where(ProposalItem.proposal_id == proposal.id)
        .order_by(ProposalItem.position)
    ).all()
    result_items = []
    for item in items:
        reviews = session.scalars(
            select(ReviewDecision)
            .where(ReviewDecision.proposal_item_id == item.id)
            .order_by(ReviewDecision.recorded_at, ReviewDecision.id)
        ).all()
        result_items.append(
            {
                "id": item.id,
                "position": item.position,
                "command_type": item.command_type,
                "payload": _public_payload(item.payload_json),
                "preconditions": item.preconditions_json,
                "status": item.status,
                "validation_errors": item.validation_errors_json,
                "created_canonical_ids": item.created_canonical_ids_json,
                "effective_outcome": effective_review_outcome(session, item.id),
                "reviews": [
                    {
                        "id": review.id,
                        "reviewer_actor_id": review.reviewer_actor_id,
                        "decision": review.decision,
                        "rationale": review.rationale,
                        "recorded_at": review.recorded_at,
                    }
                    for review in reviews
                ],
            }
        )
    return ProposalResponse.model_validate(
        {
            "id": proposal.id,
            "namespace_id": proposal.namespace_id,
            "proposer_actor_id": proposal.proposer_actor_id,
            "title": proposal.title,
            "description": proposal.description,
            "base_revision_token": proposal.base_revision_token,
            "status": proposal.status,
            "recorded_at": _utc_datetime(proposal.recorded_at),
            "submitted_at": _utc_datetime(proposal.submitted_at),
            "applied_at": _utc_datetime(proposal.applied_at),
            "applied_by_actor_id": proposal.applied_by_actor_id,
            "items": result_items,
        }
    )


@router.get("/health/live", response_model=HealthResponse)
def live() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse)
def ready(session: DbSession) -> HealthResponse:
    session.execute(text("SELECT 1"))
    return HealthResponse(status="ready")


@router.get("/namespaces/{namespace_id}", response_model=NamespaceResponse)
def get_namespace(namespace_id: str, session: DbSession) -> NamespaceResponse:
    namespace = session.get(Namespace, namespace_id)
    if namespace is None:
        from noemosyne_domain.errors import NotFoundError

        raise NotFoundError("namespace.not_found", "Namespace not found")
    return NamespaceResponse.model_validate(
        {
            "id": namespace.id,
            "slug": namespace.slug,
            "name": namespace.name,
            "revision_token": namespace.revision_token,
            "recorded_at": namespace.recorded_at,
        }
    )


@router.get("/namespaces/{namespace_id}/actors", response_model=ActorListResponse)
def list_namespace_actors(namespace_id: str, session: DbSession) -> ActorListResponse:
    namespace = session.get(Namespace, namespace_id)
    if namespace is None:
        from noemosyne_domain.errors import NotFoundError

        raise NotFoundError("namespace.not_found", "Namespace not found")
    actors = session.scalars(
        select(Actor)
        .where(Actor.namespace_id == namespace_id)
        .order_by(Actor.display_name, Actor.id)
    ).all()
    return ActorListResponse.model_validate(
        {
            "actors": [
                {
                    "id": actor.id,
                    "namespace_id": actor.namespace_id,
                    "kind": actor.kind,
                    "display_name": actor.display_name,
                    "external_id": actor.external_id,
                    "provenance": actor.provenance_json,
                    "recorded_at": actor.recorded_at,
                }
                for actor in actors
            ]
        }
    )


@router.get("/claims/{claim_id}", response_model=ClaimResponse)
def get_claim(claim_id: str, session: DbSession) -> ClaimResponse:
    claim = session.get(Claim, claim_id)
    if claim is None or claim.status != "accepted":
        from noemosyne_domain.errors import NotFoundError

        raise NotFoundError("claim.not_found", "Claim not found")
    version = session.get(ClaimVersion, claim.current_version_id)
    if version is None:
        from noemosyne_domain.errors import DomainError

        raise DomainError("claim.incomplete", "Accepted claim has no current version")
    return ClaimResponse.model_validate(
        {
            "id": claim.id,
            "namespace_id": claim.namespace_id,
            "claim_form": claim.claim_form,
            "status": claim.status,
            "current_version": {
                "id": version.id,
                "version_number": version.version_number,
                "wording": version.wording,
                "scope": version.scope_json,
                "valid_from": version.valid_from,
                "recorded_at": version.recorded_at,
                "supersedes_id": version.supersedes_id,
            },
        }
    )


@router.get("/claims/{claim_id}/context", response_model=ContextBundleResponse)
def get_claim_context(
    claim_id: str,
    session: DbSession,
    knowledge_cutoff: datetime | None = None,
    domain_time: datetime | None = None,
    max_evidence_per_stance: Annotated[int, Query(ge=1, le=100)] = 20,
    include_history_summary: bool = True,
    include_open_challenges: bool = True,
) -> ContextBundleResponse:
    cutoff = knowledge_cutoff or datetime.now(UTC)
    domain = domain_time or cutoff
    bundle = build_context_bundle(
        session,
        claim_id,
        cutoff,
        domain,
        max_evidence_per_stance,
        include_history_summary,
        include_open_challenges,
    )
    if bundle is None:
        from noemosyne_domain.errors import NotFoundError

        raise NotFoundError(
            "claim.not_found_at_cutoff", "Claim was not known at the requested cutoff"
        )
    return ContextBundleResponse.model_validate(bundle)


@router.get("/claims/{claim_id}/history", response_model=ClaimHistoryResponse)
def get_claim_history(
    claim_id: str,
    session: DbSession,
    cutoff: datetime | None = None,
    from_cutoff: datetime | None = None,
    to_cutoff: datetime | None = None,
) -> ClaimHistoryResponse:
    if cutoff is not None and (from_cutoff is not None or to_cutoff is not None):
        from noemosyne_domain.errors import DomainError

        raise DomainError("history.invalid_range", "Use cutoff or from_cutoff/to_cutoff, not both")
    query = select(EpistemicAssessment).where(EpistemicAssessment.claim_id == claim_id)
    if cutoff is not None:
        query = query.where(EpistemicAssessment.recorded_at <= cutoff)
    if from_cutoff is not None:
        query = query.where(EpistemicAssessment.recorded_at >= from_cutoff)
    if to_cutoff is not None:
        query = query.where(EpistemicAssessment.recorded_at <= to_cutoff)
    rows = session.scalars(
        query.order_by(EpistemicAssessment.recorded_at, EpistemicAssessment.id)
    ).all()
    timeline = [
        {
            "id": row.id,
            "verdict": row.verdict,
            "rationale": row.rationale,
            "recorded_at": row.recorded_at,
            "valid_from": row.valid_from,
            "supersedes_id": row.supersedes_id,
        }
        for row in rows
    ]
    comparison = None
    if len(timeline) >= 2:
        comparison = {"from": timeline[0], "to": timeline[-1]}
    revision_query = select(RevisionEvent).where(RevisionEvent.claim_id == claim_id)
    if cutoff is not None:
        revision_query = revision_query.where(RevisionEvent.recorded_at <= cutoff)
    if from_cutoff is not None:
        revision_query = revision_query.where(RevisionEvent.recorded_at >= from_cutoff)
    if to_cutoff is not None:
        revision_query = revision_query.where(RevisionEvent.recorded_at <= to_cutoff)
    revisions = session.scalars(
        revision_query.order_by(RevisionEvent.recorded_at, RevisionEvent.id)
    ).all()
    return ClaimHistoryResponse.model_validate(
        {
            "claim_id": claim_id,
            "timeline": timeline,
            "revisions": [
                {
                    "id": revision.id,
                    "before_assessment_id": revision.before_assessment_id,
                    "after_assessment_id": revision.after_assessment_id,
                    "rationale": revision.rationale,
                    "recorded_at": revision.recorded_at,
                }
                for revision in revisions
            ],
            "comparison": comparison,
        }
    )


@router.post("/claims:search", response_model=SearchResponse)
def search_claims(body: SearchRequest, session: DbSession) -> SearchResponse:
    normalized = body.query.strip().lower()
    substring_match = func.lower(ClaimVersion.wording).contains(normalized)
    predicate = substring_match
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        predicate = or_(
            ClaimVersion.wording.match(body.query, postgresql_regconfig="simple"),
            substring_match,
        )
    query = (
        select(Claim, ClaimVersion)
        .join(ClaimVersion, Claim.current_version_id == ClaimVersion.id)
        .where(
            Claim.namespace_id == body.namespace_id,
            Claim.status == "accepted",
            predicate,
        )
        .order_by(ClaimVersion.wording, Claim.id)
        .limit(body.limit)
    )
    rows = session.execute(query).all()
    return SearchResponse.model_validate(
        {
            "query": body.query,
            "results": [
                {
                    "claim_id": claim.id,
                    "wording": version.wording,
                    "scope": version.scope_json,
                    "scores": {"substring": 1.0, "lexical": None, "semantic": None},
                }
                for claim, version in rows
            ],
        }
    )


@router.post("/graph:trace", response_model=GraphTraceResponse)
def graph_trace(body: GraphTraceRequest, session: DbSession) -> GraphTraceResponse:
    return GraphTraceResponse.model_validate(
        trace_claim_graph(
            session, body.start_claim_id, body.relation_types, body.max_depth, body.max_nodes
        )
    )


@router.get("/sources/{source_id}", response_model=SourceResponse)
def get_source(source_id: str, session: DbSession) -> SourceResponse:
    source = session.get(SourceArtifact, source_id)
    if source is None or source.status != "accepted":
        from noemosyne_domain.errors import NotFoundError

        raise NotFoundError("source.not_found", "Source not found")
    fragments = session.scalars(
        select(SourceFragment)
        .where(SourceFragment.source_artifact_id == source.id, SourceFragment.status == "accepted")
        .order_by(SourceFragment.id)
    ).all()
    return SourceResponse.model_validate(
        {
            "id": source.id,
            "kind": source.kind,
            "title": source.title,
            "canonical_uri": source.canonical_uri,
            "authors": source.authors_json,
            "license_basis": source.license_basis,
            "access": source.access_json,
            "fragments": [
                {
                    "id": fragment.id,
                    "locator": fragment.locator_json,
                    "text_hash": fragment.text_hash,
                    "license_basis": fragment.license_basis,
                }
                for fragment in fragments
            ],
        }
    )


@router.get("/activity", response_model=ActivityResponse)
def get_activity(
    session: DbSession,
    namespace_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ActivityResponse:
    query = select(AuditEvent)
    if namespace_id is not None:
        query = query.where(AuditEvent.namespace_id == namespace_id)
    rows = session.scalars(
        query.order_by(AuditEvent.recorded_at.desc(), AuditEvent.id).limit(limit)
    ).all()
    return ActivityResponse.model_validate(
        {
            "events": [
                {
                    "id": row.id,
                    "event_type": row.event_type,
                    "object_type": row.object_type,
                    "object_id": row.object_id,
                    "actor_id": row.actor_id,
                    "proposal_id": row.proposal_id,
                    "detail": row.detail_json,
                    "recorded_at": row.recorded_at,
                }
                for row in rows
            ]
        }
    )


@router.post("/proposals", status_code=201, response_model=ProposalResponse)
def create_proposal(body: ProposalCreate, session: DbSession) -> ProposalResponse:
    namespace = session.get(Namespace, body.namespace_id)
    actor = session.get(Actor, body.proposer_actor_id)
    if namespace is None or actor is None or actor.namespace_id != namespace.id:
        from noemosyne_domain.errors import DomainError

        raise DomainError("proposal.invalid_provenance", "Namespace and proposer actor must exist")
    proposal = Proposal(
        namespace_id=body.namespace_id,
        proposer_actor_id=body.proposer_actor_id,
        title=body.title,
        description=body.description,
        base_revision_token=body.base_revision_token,
    )
    session.add(proposal)
    session.commit()
    return _serialize_proposal(session, proposal)


@router.post("/proposals/{proposal_id}/items", status_code=201, response_model=ProposalResponse)
def add_proposal_item(
    proposal_id: str, body: ProposalItemCreate, session: DbSession
) -> ProposalResponse:
    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        from noemosyne_domain.errors import NotFoundError

        raise NotFoundError("proposal.not_found", "Proposal not found")
    if proposal.status != "draft":
        from noemosyne_domain.errors import ConflictError

        raise ConflictError("proposal.immutable", "Submitted proposals are immutable")
    position = int(
        session.scalar(
            select(func.count())
            .select_from(ProposalItem)
            .where(ProposalItem.proposal_id == proposal.id)
        )
        or 0
    )
    item = ProposalItem(
        proposal_id=proposal.id,
        position=position,
        command_type=body.command_type,
        payload_json=body.payload,
        preconditions_json=body.preconditions,
    )
    session.add(item)
    session.commit()
    return _serialize_proposal(session, proposal)


@router.post("/proposals/{proposal_id}:validate", response_model=ProposalResponse)
def validate_proposal_route(proposal_id: str, session: DbSession) -> ProposalResponse:
    return _serialize_proposal(session, validate_proposal(session, proposal_id))


@router.post("/proposals/{proposal_id}:submit", response_model=ProposalResponse)
def submit_proposal_route(proposal_id: str, session: DbSession) -> ProposalResponse:
    return _serialize_proposal(session, submit_proposal(session, proposal_id))


@router.get("/proposals/{proposal_id}", response_model=ProposalResponse)
def get_proposal(proposal_id: str, session: DbSession) -> ProposalResponse:
    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        from noemosyne_domain.errors import NotFoundError

        raise NotFoundError("proposal.not_found", "Proposal not found")
    return _serialize_proposal(session, proposal)


@router.get("/proposals", response_model=ProposalListResponse)
def list_proposals(session: DbSession, status: str | None = None) -> ProposalListResponse:
    query = select(Proposal)
    if status is not None:
        query = query.where(Proposal.status == status)
    rows = session.scalars(query.order_by(Proposal.recorded_at.desc(), Proposal.id)).all()
    return ProposalListResponse(proposals=[_serialize_proposal(session, row) for row in rows])


@router.post("/proposals/{proposal_id}/reviews", status_code=201, response_model=ProposalResponse)
def review_proposal(proposal_id: str, body: ReviewCreate, session: DbSession) -> ProposalResponse:
    add_review(
        session,
        proposal_id,
        body.proposal_item_id,
        body.reviewer_actor_id,
        body.decision,
        body.rationale,
    )
    proposal = session.get(Proposal, proposal_id)
    assert proposal is not None
    return _serialize_proposal(session, proposal)


@router.post("/proposals/{proposal_id}:apply", response_model=ProposalResponse)
def apply_proposal_route(
    proposal_id: str, body: ApplyRequest, session: DbSession
) -> ProposalResponse:
    return _serialize_proposal(
        session, apply_proposal(session, proposal_id, body.applied_by_actor_id)
    )
