"""Transactional proposal validation, review, and canonical application."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from noemosyne_domain.errors import ConflictError, DomainError, NotFoundError
from noemosyne_domain.models import EvidenceLink as DomainEvidenceLink
from noemosyne_domain.models import (
    EvidenceStance,
    ReviewDecisionKind,
    Verdict,
    review_outcome,
    validate_assessment_inputs,
    validate_evidence_item_content,
    validate_relation,
)
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .models import (
    Actor,
    Argument,
    ArgumentPremise,
    Assertion,
    AssessmentInput,
    AssessmentPolicy,
    AuditEvent,
    Challenge,
    Claim,
    ClaimRelation,
    ClaimVersion,
    EpistemicAssessment,
    EvidenceDependencyGroup,
    EvidenceDependencyMember,
    EvidenceItem,
    EvidenceItemSource,
    EvidenceLink,
    Namespace,
    Proposal,
    ProposalItem,
    Question,
    ReviewDecision,
    RevisionEvent,
    SourceArtifact,
    SourceFragment,
    new_id,
)

SUPPORTED_COMMANDS = frozenset(
    {
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
    }
)


def _parse_time(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise DomainError("proposal.invalid_time", f"{field} must be an ISO 8601 timestamp")
    if result.tzinfo is None:
        raise DomainError("time.timezone_required", f"{field} must include a timezone")
    return result.astimezone(UTC)


def validate_command(command_type: str, payload: dict[str, Any]) -> None:
    """Parse candidate JSON into the named safe command shape without executing it."""
    if command_type not in SUPPORTED_COMMANDS:
        raise DomainError("proposal.command_not_allowed", f"Unsupported command {command_type!r}")
    required: dict[str, set[str]] = {
        "CreateClaim": {"wording", "scope_json", "valid_from"},
        "AddClaimVersion": {"claim_id", "wording", "scope_json", "valid_from"},
        "RegisterSourceArtifact": {"title", "kind", "canonical_uri", "license_basis"},
        "AddSourceFragment": {"source_artifact_id", "locator_json", "license_basis"},
        "CreateEvidenceItem": {"kind"},
        "CreateEvidenceDependencyGroup": {"label", "dependency_type"},
        "AddEvidenceDependencyMember": {"dependency_group_id", "evidence_item_id"},
        "LinkEvidenceToClaim": {
            "claim_id",
            "evidence_item_id",
            "evaluator_actor_id",
            "assessment_policy_id",
            "stance",
            "directness",
            "strength_band",
            "scope_match",
        },
        "RelateClaims": {"source_claim_id", "target_claim_id", "relation_type", "context_json"},
        "AddAssertion": {"claim_id", "actor_id", "stance", "asserted_at"},
        "CreateArgument": {
            "conclusion_claim_id",
            "author_actor_id",
            "inference_scheme",
            "premise_ids",
            "rationale",
        },
        "RaiseChallenge": {
            "target_type",
            "target_id",
            "category",
            "explanation",
            "raised_by_actor_id",
        },
        "CreateAssessment": {
            "claim_id",
            "assessor_actor_id",
            "policy_id",
            "verdict",
            "rationale",
            "input_ids",
            "valid_from",
        },
        "CreateRevisionEvent": {"claim_id", "after_assessment_id", "rationale"},
        "CreateQuestion": {"wording", "importance_rationale"},
    }
    missing = required[command_type] - payload.keys()
    if missing:
        raise DomainError(
            "proposal.missing_fields", f"Missing fields: {', '.join(sorted(missing))}"
        )
    if command_type in {"CreateClaim", "AddClaimVersion"}:
        if not str(payload["wording"]).strip():
            raise DomainError("claim.wording_required", "Claim wording cannot be empty")
        if not isinstance(payload["scope_json"], dict):
            raise DomainError("claim.invalid_scope", "scope_json must be an object")
        _parse_time(payload["valid_from"], "valid_from")
    elif command_type == "RegisterSourceArtifact":
        if (
            not str(payload["title"]).strip()
            or not str(payload["canonical_uri"]).strip()
            or not str(payload["license_basis"]).strip()
        ):
            raise DomainError(
                "source.incomplete_metadata",
                "A source requires title, canonical URI, and license basis",
            )
    elif command_type == "AddSourceFragment":
        if not isinstance(payload["locator_json"], dict) or not payload["locator_json"]:
            raise DomainError("source.locator_required", "A source fragment requires a locator")
        if not str(payload["license_basis"]).strip():
            raise DomainError(
                "source.license_required", "A source fragment requires a license basis"
            )
        if payload.get("stored_text") is not None and payload.get("text_hash") is None:
            expected = sha256(str(payload["stored_text"]).encode()).hexdigest()
            payload["text_hash"] = expected
    elif command_type == "CreateEvidenceItem":
        source_fragment_ids = tuple(payload.get("source_fragment_ids", ()))
        argument_id = payload.get("argument_id")
        validate_evidence_item_content(str(payload["kind"]), source_fragment_ids, argument_id)
    elif command_type == "AddAssertion":
        if payload["stance"] not in {"asserts", "denies", "questions", "withholds"}:
            raise DomainError("assertion.invalid_stance", "Unknown assertion stance")
        _parse_time(payload["asserted_at"], "asserted_at")
    elif command_type == "CreateArgument":
        if not payload["premise_ids"]:
            raise DomainError("argument.premises_required", "An argument requires a premise")
        if not str(payload["rationale"]).strip():
            raise DomainError("argument.rationale_required", "An argument requires rationale")
    elif command_type == "RaiseChallenge":
        if not str(payload["explanation"]).strip():
            raise DomainError("challenge.explanation_required", "A challenge requires explanation")
    elif command_type == "LinkEvidenceToClaim":
        DomainEvidenceLink(
            claim_id=_as_uuid(payload["claim_id"]),
            evidence_item_id=_as_uuid(payload["evidence_item_id"]),
            evaluator_actor_id=_as_uuid(payload["evaluator_actor_id"]),
            assessment_policy_id=_as_uuid(payload["assessment_policy_id"]),
            stance=EvidenceStance(payload["stance"]),
            directness=str(payload["directness"]),
            strength_band=str(payload["strength_band"]),
            scope_match=str(payload["scope_match"]),
            caveats=tuple(payload.get("caveats", [])),
        )
    elif command_type == "RelateClaims":
        validate_relation(str(payload["relation_type"]), dict(payload["context_json"]))
    elif command_type == "CreateAssessment":
        verdict = Verdict(payload["verdict"])
        validate_assessment_inputs(
            verdict, tuple(_as_uuid(value) for value in payload["input_ids"])
        )
        _parse_time(payload["valid_from"], "valid_from")
    elif command_type == "CreateRevisionEvent":
        if payload.get("before_assessment_id") == payload["after_assessment_id"]:
            raise DomainError("revision.no_change", "A revision must change assessment identity")
    elif command_type == "CreateQuestion" and not str(payload["wording"]).strip():
        raise DomainError("question.wording_required", "A question requires wording")


def _validate_precondition_shape(preconditions: dict[str, Any]) -> None:
    allowed = {
        "claim_id",
        "claim_current_version_id",
        "source_artifact_id",
        "source_content_hash",
    }
    unknown = preconditions.keys() - allowed
    if unknown:
        raise DomainError(
            "proposal.precondition_not_allowed",
            f"Unknown preconditions: {', '.join(sorted(unknown))}",
        )
    if "claim_current_version_id" in preconditions and "claim_id" not in preconditions:
        raise DomainError(
            "proposal.precondition_target_required",
            "claim_current_version_id requires claim_id",
        )
    if "source_content_hash" in preconditions and "source_artifact_id" not in preconditions:
        raise DomainError(
            "proposal.precondition_target_required",
            "source_content_hash requires source_artifact_id",
        )


def _verify_preconditions(session: Session, item: ProposalItem) -> None:
    preconditions = item.preconditions_json
    _validate_precondition_shape(preconditions)
    if "claim_id" in preconditions:
        claim = session.scalar(
            select(Claim).where(Claim.id == preconditions["claim_id"]).with_for_update()
        )
        if claim is None or (
            "claim_current_version_id" in preconditions
            and claim.current_version_id != preconditions["claim_current_version_id"]
        ):
            raise ConflictError(
                "proposal.precondition_failed",
                f"Claim precondition failed for item {item.id}",
            )
    if "source_artifact_id" in preconditions:
        source = session.scalar(
            select(SourceArtifact)
            .where(SourceArtifact.id == preconditions["source_artifact_id"])
            .with_for_update()
        )
        if source is None or (
            "source_content_hash" in preconditions
            and source.content_hash != preconditions["source_content_hash"]
        ):
            raise ConflictError(
                "proposal.precondition_failed",
                f"Source precondition failed for item {item.id}",
            )


def _as_uuid(value: Any) -> Any:
    from uuid import UUID

    return UUID(str(value))


CandidateReferences = dict[tuple[str, str], dict[str, Any]]


def _candidate_reference(command_type: str, payload: dict[str, Any]) -> tuple[str, str] | None:
    reference_types = {
        "CreateClaim": "claim",
        "RegisterSourceArtifact": "source_artifact",
        "AddSourceFragment": "source_fragment",
        "CreateEvidenceItem": "evidence_item",
        "CreateEvidenceDependencyGroup": "dependency_group",
        "CreateArgument": "argument",
        "CreateAssessment": "assessment",
        "CreateQuestion": "question",
    }
    reference_type = reference_types.get(command_type)
    reference_id = payload.get("id")
    if reference_type is None or reference_id is None:
        return None
    return reference_type, str(reference_id)


def _reference_namespace_and_status(
    session: Session, reference_type: str, reference_id: str
) -> tuple[str, str | None] | None:
    if reference_type == "actor":
        actor = session.get(Actor, reference_id)
        return None if actor is None else (actor.namespace_id, None)
    if reference_type == "claim":
        claim = session.get(Claim, reference_id)
        return None if claim is None else (claim.namespace_id, claim.status)
    if reference_type == "source_artifact":
        source = session.get(SourceArtifact, reference_id)
        return None if source is None else (source.namespace_id, source.status)
    if reference_type == "evidence_item":
        evidence = session.get(EvidenceItem, reference_id)
        return None if evidence is None else (evidence.namespace_id, evidence.status)
    if reference_type == "dependency_group":
        group = session.get(EvidenceDependencyGroup, reference_id)
        return None if group is None else (group.namespace_id, group.status)
    if reference_type == "assessment_policy":
        policy = session.get(AssessmentPolicy, reference_id)
        return None if policy is None else (policy.namespace_id, policy.status)
    if reference_type == "argument":
        argument = session.get(Argument, reference_id)
        return None if argument is None else (argument.namespace_id, argument.status)
    if reference_type == "challenge":
        challenge = session.get(Challenge, reference_id)
        return None if challenge is None else (challenge.namespace_id, challenge.status)
    if reference_type == "question":
        question = session.get(Question, reference_id)
        return None if question is None else (question.namespace_id, question.status)
    if reference_type == "source_fragment":
        result = session.execute(
            select(SourceArtifact.namespace_id, SourceFragment.status)
            .join(SourceFragment, SourceFragment.source_artifact_id == SourceArtifact.id)
            .where(SourceFragment.id == reference_id)
        ).one_or_none()
    elif reference_type == "evidence_link":
        result = session.execute(
            select(Claim.namespace_id, EvidenceLink.status)
            .join(EvidenceLink, EvidenceLink.claim_id == Claim.id)
            .where(EvidenceLink.id == reference_id)
        ).one_or_none()
    elif reference_type == "assessment":
        result = session.execute(
            select(Claim.namespace_id, EpistemicAssessment.status)
            .join(EpistemicAssessment, EpistemicAssessment.claim_id == Claim.id)
            .where(EpistemicAssessment.id == reference_id)
        ).one_or_none()
    elif reference_type == "claim_relation":
        result = session.execute(
            select(Claim.namespace_id, ClaimRelation.status)
            .join(ClaimRelation, ClaimRelation.source_claim_id == Claim.id)
            .where(ClaimRelation.id == reference_id)
        ).one_or_none()
    else:
        raise DomainError(
            "reference.type_not_allowed", f"Unsupported reference type {reference_type!r}"
        )
    if result is None:
        return None
    return str(result[0]), str(result[1])


def _require_reference(
    session: Session,
    namespace_id: str,
    reference_type: str,
    reference_id: Any,
    candidates: CandidateReferences,
) -> None:
    normalized_id = str(reference_id)
    if (reference_type, normalized_id) in candidates:
        return
    resolved = _reference_namespace_and_status(session, reference_type, normalized_id)
    if resolved is None:
        raise DomainError(
            "reference.not_found",
            f"Referenced {reference_type} {normalized_id} does not exist",
        )
    referenced_namespace, status = resolved
    if referenced_namespace != namespace_id:
        raise DomainError(
            "reference.namespace_mismatch",
            f"Referenced {reference_type} does not belong to the proposal namespace",
        )
    if status is not None and status != "accepted":
        raise DomainError(
            "reference.not_accepted",
            f"Referenced {reference_type} must be accepted",
        )


def _require_source_provenance(
    session: Session,
    namespace_id: str,
    fragment_id: Any,
    candidates: CandidateReferences,
) -> None:
    normalized_id = str(fragment_id)
    candidate = candidates.get(("source_fragment", normalized_id))
    if candidate is not None:
        if not candidate.get("locator_json") or not str(candidate.get("license_basis", "")).strip():
            raise DomainError(
                "evidence.incomplete_source_provenance",
                "Evidence fragments require a locator and license basis",
            )
        if candidate.get("stored_text") is not None and not candidate.get("text_hash"):
            raise DomainError(
                "evidence.incomplete_source_provenance",
                "Stored fragment text requires a text hash",
            )
        _require_reference(
            session,
            namespace_id,
            "source_artifact",
            candidate["source_artifact_id"],
            candidates,
        )
        return
    _require_reference(session, namespace_id, "source_fragment", normalized_id, candidates)
    row = session.execute(
        select(SourceFragment, SourceArtifact)
        .join(SourceArtifact, SourceArtifact.id == SourceFragment.source_artifact_id)
        .where(SourceFragment.id == normalized_id)
    ).one()
    fragment, source = row
    if (
        not fragment.locator_json
        or not str(fragment.license_basis).strip()
        or (fragment.stored_text is not None and not fragment.text_hash)
        or not str(source.title).strip()
        or not str(source.canonical_uri).strip()
        or not str(source.license_basis).strip()
    ):
        raise DomainError(
            "evidence.incomplete_source_provenance",
            "Evidence fragments require complete source metadata, locator, hash, and license basis",
        )


def _require_evidence_provenance(
    session: Session,
    namespace_id: str,
    evidence_item_id: Any,
    candidates: CandidateReferences,
) -> None:
    normalized_id = str(evidence_item_id)
    candidate = candidates.get(("evidence_item", normalized_id))
    if candidate is not None:
        if candidate["kind"] == "source_fragment":
            for fragment_id in candidate.get("source_fragment_ids", []):
                _require_source_provenance(session, namespace_id, fragment_id, candidates)
        else:
            _require_reference(
                session,
                namespace_id,
                "argument",
                candidate.get("argument_id"),
                candidates,
            )
        return
    _require_reference(session, namespace_id, "evidence_item", normalized_id, candidates)
    evidence = session.get(EvidenceItem, normalized_id)
    assert evidence is not None
    if evidence.kind == "source_fragment":
        fragment_ids = session.scalars(
            select(EvidenceItemSource.source_fragment_id).where(
                EvidenceItemSource.evidence_item_id == evidence.id,
                EvidenceItemSource.status == "accepted",
            )
        ).all()
        if not fragment_ids:
            raise DomainError(
                "evidence.unresolvable_provenance",
                "Source-fragment evidence has no accepted fragments",
            )
        for fragment_id in fragment_ids:
            _require_source_provenance(session, namespace_id, fragment_id, candidates)
    elif evidence.kind == "argument" and evidence.argument_id is not None:
        _require_reference(session, namespace_id, "argument", evidence.argument_id, candidates)
        premise_count = session.scalar(
            select(func.count())
            .select_from(ArgumentPremise)
            .where(
                ArgumentPremise.argument_id == evidence.argument_id,
                ArgumentPremise.status == "accepted",
            )
        )
        if not premise_count:
            raise DomainError(
                "evidence.unresolvable_provenance",
                "Argument evidence requires an accepted argument with premises",
            )
    else:
        raise DomainError(
            "evidence.unresolvable_provenance",
            "Evidence item content does not match its kind",
        )


def _require_assessment_for_claim(
    session: Session,
    namespace_id: str,
    assessment_id: Any,
    claim_id: Any,
    candidates: CandidateReferences,
) -> None:
    _require_reference(session, namespace_id, "assessment", assessment_id, candidates)
    candidate = candidates.get(("assessment", str(assessment_id)))
    assessment_claim_id = (
        str(candidate["claim_id"])
        if candidate is not None
        else session.scalar(
            select(EpistemicAssessment.claim_id).where(EpistemicAssessment.id == str(assessment_id))
        )
    )
    if assessment_claim_id != str(claim_id):
        raise DomainError(
            "revision.claim_mismatch",
            "Assessment supersession and revisions must stay on one claim",
        )


def _validate_command_references(
    session: Session,
    proposal: Proposal,
    item: ProposalItem,
    candidates: CandidateReferences,
) -> None:
    payload = item.payload_json
    namespace_id = proposal.namespace_id

    def require(reference_type: str, value: Any) -> None:
        _require_reference(session, namespace_id, reference_type, value, candidates)

    if item.preconditions_json.get("claim_id") is not None:
        require("claim", item.preconditions_json["claim_id"])
    if item.preconditions_json.get("source_artifact_id") is not None:
        require("source_artifact", item.preconditions_json["source_artifact_id"])

    command = item.command_type
    if command == "AddClaimVersion":
        require("claim", payload["claim_id"])
    elif command == "AddSourceFragment":
        require("source_artifact", payload["source_artifact_id"])
    elif command == "CreateEvidenceItem":
        if payload["kind"] == "source_fragment":
            for fragment_id in payload.get("source_fragment_ids", []):
                _require_source_provenance(session, namespace_id, fragment_id, candidates)
        else:
            require("argument", payload["argument_id"])
    elif command == "AddEvidenceDependencyMember":
        require("dependency_group", payload["dependency_group_id"])
        require("evidence_item", payload["evidence_item_id"])
    elif command == "LinkEvidenceToClaim":
        require("claim", payload["claim_id"])
        _require_evidence_provenance(session, namespace_id, payload["evidence_item_id"], candidates)
        require("actor", payload["evaluator_actor_id"])
        require("assessment_policy", payload["assessment_policy_id"])
        if payload.get("dependency_group_id") is not None:
            require("dependency_group", payload["dependency_group_id"])
    elif command == "RelateClaims":
        require("claim", payload["source_claim_id"])
        require("claim", payload["target_claim_id"])
    elif command == "AddAssertion":
        require("claim", payload["claim_id"])
        require("actor", payload["actor_id"])
        if payload.get("source_fragment_id") is not None:
            _require_source_provenance(
                session, namespace_id, payload["source_fragment_id"], candidates
            )
    elif command == "CreateArgument":
        require("claim", payload["conclusion_claim_id"])
        require("actor", payload["author_actor_id"])
        premise_type = payload.get("premise_type", "claim")
        if premise_type not in {"claim", "evidence_item"}:
            raise DomainError(
                "argument.invalid_premise_type",
                "Argument premises must be claims or evidence items",
            )
        for premise_id in payload["premise_ids"]:
            require(premise_type, premise_id)
    elif command == "RaiseChallenge":
        target_types = {
            "claim",
            "source_artifact",
            "source_fragment",
            "evidence_item",
            "evidence_link",
            "argument",
            "assessment",
            "claim_relation",
            "question",
        }
        target_type = str(payload["target_type"])
        if target_type not in target_types:
            raise DomainError(
                "challenge.invalid_target_type", "Challenge target type is not supported in M1"
            )
        require(target_type, payload["target_id"])
        require("actor", payload["raised_by_actor_id"])
    elif command == "CreateAssessment":
        require("claim", payload["claim_id"])
        require("actor", payload["assessor_actor_id"])
        require("assessment_policy", payload["policy_id"])
        input_type = payload.get("input_type", "evidence_link")
        if input_type not in {"evidence_link", "argument", "challenge"}:
            raise DomainError(
                "assessment.invalid_input_type",
                "Assessment inputs must be evidence links, arguments, or challenges",
            )
        for input_id in payload["input_ids"]:
            require(input_type, input_id)
        if payload.get("supersedes_id") is not None:
            _require_assessment_for_claim(
                session,
                namespace_id,
                payload["supersedes_id"],
                payload["claim_id"],
                candidates,
            )
    elif command == "CreateRevisionEvent":
        require("claim", payload["claim_id"])
        if payload.get("before_assessment_id") is not None:
            _require_assessment_for_claim(
                session,
                namespace_id,
                payload["before_assessment_id"],
                payload["claim_id"],
                candidates,
            )
        _require_assessment_for_claim(
            session,
            namespace_id,
            payload["after_assessment_id"],
            payload["claim_id"],
            candidates,
        )
        after_candidate = candidates.get(("assessment", str(payload["after_assessment_id"])))
        after_supersedes_id = (
            after_candidate.get("supersedes_id")
            if after_candidate is not None
            else session.scalar(
                select(EpistemicAssessment.supersedes_id).where(
                    EpistemicAssessment.id == str(payload["after_assessment_id"])
                )
            )
        )
        if str(after_supersedes_id or "") != str(payload.get("before_assessment_id") or ""):
            raise DomainError(
                "revision.chain_mismatch",
                "Revision before/after assessments must match the supersession chain",
            )
        if payload.get("author_actor_id") is not None:
            require("actor", payload["author_actor_id"])


def _validate_actor_namespace(
    session: Session, namespace_id: str, actor_id: str, code: str
) -> None:
    actor = session.get(Actor, actor_id)
    if actor is None:
        raise DomainError("reference.not_found", "Referenced actor does not exist")
    if actor.namespace_id != namespace_id:
        raise DomainError(code, "Actor does not belong to the proposal namespace")


def validate_proposal(session: Session, proposal_id: str) -> Proposal:
    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        raise NotFoundError("proposal.not_found", "Proposal not found")
    if proposal.status not in {"draft", "ready"}:
        raise ConflictError("proposal.immutable", "Only a draft proposal can be validated")
    items = session.scalars(
        select(ProposalItem)
        .where(ProposalItem.proposal_id == proposal.id)
        .order_by(ProposalItem.position)
    ).all()
    if not items:
        raise DomainError("proposal.items_required", "A proposal must contain at least one item")
    _validate_actor_namespace(
        session,
        proposal.namespace_id,
        proposal.proposer_actor_id,
        "proposal.proposer_namespace_mismatch",
    )
    all_valid = True
    candidates: CandidateReferences = {}
    for item in items:
        try:
            validate_command(item.command_type, item.payload_json)
            _validate_precondition_shape(item.preconditions_json)
            _validate_command_references(session, proposal, item, candidates)
            item.status = "valid"
            item.validation_errors_json = []
            candidate = _candidate_reference(item.command_type, item.payload_json)
            if candidate is not None:
                if (
                    candidate in candidates
                    or _reference_namespace_and_status(session, candidate[0], candidate[1])
                    is not None
                ):
                    raise DomainError(
                        "reference.identity_conflict",
                        f"Candidate {candidate[0]} identity already exists",
                    )
                candidates[candidate] = item.payload_json
        except (DomainError, ValueError) as error:
            all_valid = False
            item.status = "invalid"
            item.validation_errors_json = [
                {"code": getattr(error, "code", "proposal.invalid_payload"), "detail": str(error)}
            ]
    proposal.status = "ready" if all_valid else "draft"
    session.commit()
    return proposal


def submit_proposal(session: Session, proposal_id: str) -> Proposal:
    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        raise NotFoundError("proposal.not_found", "Proposal not found")
    if proposal.status != "ready":
        raise ConflictError("proposal.not_ready", "Validate all proposal items before submission")
    proposal.status = "in_review"
    proposal.submitted_at = datetime.now(UTC)
    session.commit()
    return proposal


def add_review(
    session: Session,
    proposal_id: str,
    item_id: str,
    reviewer_actor_id: str,
    decision: str,
    rationale: str,
) -> ReviewDecision:
    proposal = session.scalar(select(Proposal).where(Proposal.id == proposal_id).with_for_update())
    item = session.get(ProposalItem, item_id)
    if proposal is None or item is None or item.proposal_id != proposal.id:
        raise NotFoundError("proposal.item_not_found", "Proposal item not found")
    if proposal.status != "in_review":
        raise ConflictError("proposal.not_in_review", "Proposal is not open for review")
    if reviewer_actor_id == proposal.proposer_actor_id:
        raise DomainError(
            "review.separation_of_duty", "A proposer cannot review their own proposal"
        )
    _validate_actor_namespace(
        session,
        proposal.namespace_id,
        reviewer_actor_id,
        "review.reviewer_namespace_mismatch",
    )
    try:
        ReviewDecisionKind(decision)
    except ValueError as error:
        raise DomainError("review.invalid_decision", "Unknown review decision") from error
    if not rationale.strip():
        raise DomainError("review.rationale_required", "A review rationale is required")
    review = ReviewDecision(
        proposal_item_id=item.id,
        reviewer_actor_id=reviewer_actor_id,
        decision=decision,
        rationale=rationale,
    )
    session.add(review)
    session.commit()
    return review


def _effective_decision(
    session: Session, item_id: str
) -> tuple[ReviewDecisionKind | None, list[ReviewDecision]]:
    decisions = list(
        session.scalars(
            select(ReviewDecision)
            .where(ReviewDecision.proposal_item_id == item_id)
            .order_by(ReviewDecision.recorded_at, ReviewDecision.id)
        )
    )
    outcome = review_outcome(tuple(ReviewDecisionKind(decision.decision) for decision in decisions))
    return outcome, decisions


def effective_review_outcome(session: Session, item_id: str) -> str | None:
    """Return the shared conservative domain outcome for a proposal item."""
    outcome, _ = _effective_decision(session, item_id)
    return None if outcome is None else outcome.value


def apply_proposal(session: Session, proposal_id: str, applied_by_actor_id: str) -> Proposal:
    """Apply all review-accepted items atomically and idempotently."""
    try:
        proposal = session.scalar(
            select(Proposal).where(Proposal.id == proposal_id).with_for_update()
        )
        if proposal is None:
            raise NotFoundError("proposal.not_found", "Proposal not found")
        if proposal.status in {"accepted", "partially_accepted", "rejected"}:
            return proposal
        if proposal.status == "stale":
            raise ConflictError(
                "proposal.stale_base_revision", "Namespace changed after proposal creation"
            )
        if proposal.status != "in_review":
            raise ConflictError("proposal.not_in_review", "Proposal must be submitted before apply")
        namespace = session.scalar(
            select(Namespace).where(Namespace.id == proposal.namespace_id).with_for_update()
        )
        if namespace is None:
            raise NotFoundError("namespace.not_found", "Namespace not found")
        _validate_actor_namespace(
            session,
            proposal.namespace_id,
            proposal.proposer_actor_id,
            "proposal.proposer_namespace_mismatch",
        )
        _validate_actor_namespace(
            session,
            proposal.namespace_id,
            applied_by_actor_id,
            "proposal.applier_namespace_mismatch",
        )
        if namespace.revision_token != proposal.base_revision_token:
            proposal.status = "stale"
            raise ConflictError(
                "proposal.stale_base_revision", "Namespace changed after proposal creation"
            )
        items = session.scalars(
            select(ProposalItem)
            .where(ProposalItem.proposal_id == proposal.id)
            .order_by(ProposalItem.position)
            .with_for_update()
        ).all()
        accepted: list[tuple[ProposalItem, str]] = []
        for item in items:
            outcome, decisions = _effective_decision(session, item.id)
            for decision in decisions:
                if decision.reviewer_actor_id == proposal.proposer_actor_id:
                    raise DomainError(
                        "review.separation_of_duty", "A proposer cannot review their own item"
                    )
                _validate_actor_namespace(
                    session,
                    proposal.namespace_id,
                    decision.reviewer_actor_id,
                    "review.reviewer_namespace_mismatch",
                )
            if outcome is None:
                raise DomainError(
                    "review.substantive_decision_required",
                    "Every proposal item needs an accept, reject, or request-changes decision",
                )
            if outcome is ReviewDecisionKind.ACCEPT:
                accepting_review = next(
                    decision for decision in decisions if decision.decision == "accept"
                )
                accepted.append((item, accepting_review.reviewer_actor_id))
            else:
                item.status = "rejected"
        if not accepted:
            session.flush()
            proposal.status = "rejected"
            proposal.applied_at = datetime.now(UTC)
            proposal.applied_by_actor_id = applied_by_actor_id
            session.commit()
            return proposal
        for item, reviewer_actor_id in accepted:
            validate_command(item.command_type, item.payload_json)
            _validate_command_references(session, proposal, item, {})
            _verify_preconditions(session, item)
            created_ids = _execute_command(
                session,
                proposal,
                item,
                reviewer_actor_id,
            )
            item.created_canonical_ids_json = created_ids
            item.status = "accepted"
        session.flush()
        namespace.revision_token += 1
        proposal.status = "accepted" if len(accepted) == len(items) else "partially_accepted"
        proposal.applied_at = datetime.now(UTC)
        proposal.applied_by_actor_id = applied_by_actor_id
        session.add(
            AuditEvent(
                namespace_id=namespace.id,
                actor_id=applied_by_actor_id,
                event_type="proposal.applied",
                object_type="proposal",
                object_id=proposal.id,
                proposal_id=proposal.id,
                detail_json={"accepted_item_ids": [item.id for item, _ in accepted]},
            )
        )
        session.commit()
        return proposal
    except ConflictError as error:
        session.rollback()
        if error.code in {"proposal.stale_base_revision", "proposal.precondition_failed"}:
            stale_proposal = session.scalar(
                select(Proposal).where(Proposal.id == proposal_id).with_for_update()
            )
            if stale_proposal is not None and stale_proposal.status == "in_review":
                stale_items = session.scalars(
                    select(ProposalItem).where(ProposalItem.proposal_id == proposal_id)
                ).all()
                for stale_item in stale_items:
                    stale_item.status = "stale"
                session.flush()
                stale_proposal.status = "stale"
                session.commit()
        raise
    except Exception:
        session.rollback()
        raise


def _execute_command(
    session: Session,
    proposal: Proposal,
    item: ProposalItem,
    reviewer_actor_id: str,
) -> list[str]:
    payload = item.payload_json
    provenance = {"status": "accepted", "proposal_item_id": item.id}
    if item.command_type == "CreateClaim":
        version_id = payload.get("version_id") or new_id()
        claim = Claim(
            id=payload.get("id"),
            namespace_id=proposal.namespace_id,
            current_version_id=version_id,
            claim_form=payload.get("claim_form", "proposition"),
            **provenance,
        )
        session.add(claim)
        session.flush()
        version = ClaimVersion(
            id=version_id,
            claim_id=claim.id,
            version_number=1,
            wording=payload["wording"],
            scope_json=payload["scope_json"],
            valid_from=_parse_time(payload["valid_from"], "valid_from"),
            **provenance,
        )
        session.add(version)
        session.flush()
        return [claim.id, version.id]
    if item.command_type == "AddClaimVersion":
        existing_claim = session.scalar(
            select(Claim).where(Claim.id == payload["claim_id"]).with_for_update()
        )
        if existing_claim is None:
            raise NotFoundError("claim.not_found", "Claim not found")
        next_version = (
            int(
                session.scalar(
                    select(func.max(ClaimVersion.version_number)).where(
                        ClaimVersion.claim_id == existing_claim.id
                    )
                )
                or 0
            )
            + 1
        )
        version = ClaimVersion(
            claim_id=existing_claim.id,
            version_number=next_version,
            wording=payload["wording"],
            scope_json=payload["scope_json"],
            valid_from=_parse_time(payload["valid_from"], "valid_from"),
            supersedes_id=existing_claim.current_version_id,
            **provenance,
        )
        session.add(version)
        session.flush()
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(
                text(
                    "SELECT noemosyne_advance_claim_version"
                    "(:claim_id, :version_id, :proposal_item_id)"
                ),
                {
                    "claim_id": existing_claim.id,
                    "version_id": version.id,
                    "proposal_item_id": item.id,
                },
            )
            session.expire(existing_claim, ["current_version_id"])
        else:
            existing_claim.current_version_id = version.id
        return [version.id]
    if item.command_type == "RegisterSourceArtifact":
        source = SourceArtifact(
            id=payload.get("id"),
            namespace_id=proposal.namespace_id,
            title=payload["title"],
            kind=payload["kind"],
            canonical_uri=payload["canonical_uri"],
            authors_json=payload.get("authors", []),
            license_basis=payload["license_basis"],
            access_json=payload.get("access_json", {}),
            content_hash=payload.get("content_hash"),
            **provenance,
        )
        session.add(source)
        session.flush()
        return [source.id]
    if item.command_type == "AddSourceFragment":
        fragment = SourceFragment(
            id=payload.get("id"),
            source_artifact_id=payload["source_artifact_id"],
            locator_json=payload["locator_json"],
            stored_text=payload.get("stored_text"),
            text_hash=payload.get("text_hash"),
            license_basis=payload["license_basis"],
            **provenance,
        )
        session.add(fragment)
        session.flush()
        return [fragment.id]
    if item.command_type == "CreateEvidenceItem":
        evidence = EvidenceItem(
            id=payload.get("id"),
            namespace_id=proposal.namespace_id,
            kind=payload["kind"],
            argument_id=payload.get("argument_id"),
            description=payload.get("description", ""),
            **provenance,
        )
        session.add(evidence)
        session.flush()
        for source_fragment_id in payload.get("source_fragment_ids", []):
            session.add(
                EvidenceItemSource(
                    evidence_item_id=evidence.id,
                    source_fragment_id=source_fragment_id,
                    **provenance,
                )
            )
        return [evidence.id]
    if item.command_type == "CreateEvidenceDependencyGroup":
        group = EvidenceDependencyGroup(
            namespace_id=proposal.namespace_id,
            label=payload["label"],
            dependency_type=payload["dependency_type"],
            rationale=payload.get("rationale", ""),
            **provenance,
        )
        session.add(group)
        session.flush()
        return [group.id]
    if item.command_type == "AddEvidenceDependencyMember":
        member = EvidenceDependencyMember(
            dependency_group_id=payload["dependency_group_id"],
            evidence_item_id=payload["evidence_item_id"],
            **provenance,
        )
        session.add(member)
        session.flush()
        return [member.id]
    if item.command_type == "LinkEvidenceToClaim":
        link = EvidenceLink(
            claim_id=payload["claim_id"],
            evidence_item_id=payload["evidence_item_id"],
            evaluator_actor_id=payload["evaluator_actor_id"],
            assessment_policy_id=payload["assessment_policy_id"],
            dependency_group_id=payload.get("dependency_group_id"),
            stance=payload["stance"],
            directness=payload["directness"],
            strength_band=payload["strength_band"],
            scope_match=payload["scope_match"],
            caveats_json=payload.get("caveats", []),
            valid_from=_parse_time(payload.get("valid_from", datetime.now(UTC)), "valid_from"),
            **provenance,
        )
        session.add(link)
        session.flush()
        return [link.id]
    if item.command_type == "RelateClaims":
        relation = ClaimRelation(
            source_claim_id=payload["source_claim_id"],
            target_claim_id=payload["target_claim_id"],
            relation_type=payload["relation_type"],
            context_json=payload["context_json"],
            reviewer_actor_id=reviewer_actor_id,
            **provenance,
        )
        session.add(relation)
        session.flush()
        return [relation.id]
    if item.command_type == "AddAssertion":
        asserted_at = _parse_time(payload["asserted_at"], "asserted_at")
        assertion = Assertion(
            claim_id=payload["claim_id"],
            actor_id=payload["actor_id"],
            source_fragment_id=payload.get("source_fragment_id"),
            stance=payload["stance"],
            asserted_at=asserted_at,
            valid_from=_parse_time(payload.get("valid_from", asserted_at), "valid_from"),
            **provenance,
        )
        session.add(assertion)
        session.flush()
        return [assertion.id]
    if item.command_type == "CreateArgument":
        argument = Argument(
            namespace_id=proposal.namespace_id,
            conclusion_claim_id=payload["conclusion_claim_id"],
            author_actor_id=payload["author_actor_id"],
            inference_scheme=payload["inference_scheme"],
            rationale=payload["rationale"],
            assumptions_json=payload.get("assumptions", []),
            defeaters_json=payload.get("defeaters", []),
            **provenance,
        )
        session.add(argument)
        session.flush()
        for position, premise_id in enumerate(payload["premise_ids"]):
            session.add(
                ArgumentPremise(
                    argument_id=argument.id,
                    premise_type=payload.get("premise_type", "claim"),
                    premise_id=premise_id,
                    position=position,
                    **provenance,
                )
            )
        return [argument.id]
    if item.command_type == "RaiseChallenge":
        challenge = Challenge(
            namespace_id=proposal.namespace_id,
            target_type=payload["target_type"],
            target_id=payload["target_id"],
            category=payload["category"],
            explanation=payload["explanation"],
            raised_by_actor_id=payload["raised_by_actor_id"],
            **provenance,
        )
        session.add(challenge)
        session.flush()
        return [challenge.id]
    if item.command_type == "CreateAssessment":
        supersedes_id = payload.get("supersedes_id")
        if supersedes_id is None:
            supersedes_id = session.scalar(
                select(EpistemicAssessment.id)
                .where(
                    EpistemicAssessment.claim_id == payload["claim_id"],
                    EpistemicAssessment.status == "accepted",
                )
                .order_by(
                    EpistemicAssessment.recorded_at.desc(),
                    EpistemicAssessment.id.desc(),
                )
                .limit(1)
            )
        assessment = EpistemicAssessment(
            claim_id=payload["claim_id"],
            assessor_actor_id=payload["assessor_actor_id"],
            policy_id=payload["policy_id"],
            verdict=payload["verdict"],
            directness=payload.get("directness", "unknown"),
            methodological_quality=payload.get("methodological_quality", "unknown"),
            independence=payload.get("independence", "unknown"),
            consistency=payload.get("consistency", "unknown"),
            scope_fit=payload.get("scope_fit", "unknown"),
            stability=payload.get("stability", "unknown"),
            rationale=payload["rationale"],
            uncertainty_drivers_json=payload.get("uncertainty_drivers", []),
            valid_from=_parse_time(payload["valid_from"], "valid_from"),
            supersedes_id=supersedes_id,
            **provenance,
        )
        session.add(assessment)
        session.flush()
        for position, input_id in enumerate(payload["input_ids"]):
            session.add(
                AssessmentInput(
                    assessment_id=assessment.id,
                    input_type=payload.get("input_type", "evidence_link"),
                    input_id=input_id,
                    position=position,
                    **provenance,
                )
            )
        revision = RevisionEvent(
            claim_id=assessment.claim_id,
            before_assessment_id=supersedes_id,
            after_assessment_id=assessment.id,
            author_actor_id=assessment.assessor_actor_id,
            reviewer_actor_id=reviewer_actor_id,
            rationale=payload.get("revision_rationale", payload["rationale"]),
            triggering_inputs_json=payload["input_ids"],
            **provenance,
        )
        session.add(revision)
        session.flush()
        return [assessment.id, revision.id]
    if item.command_type == "CreateRevisionEvent":
        revision = RevisionEvent(
            claim_id=payload["claim_id"],
            before_assessment_id=payload.get("before_assessment_id"),
            after_assessment_id=payload["after_assessment_id"],
            author_actor_id=payload.get("author_actor_id", proposal.proposer_actor_id),
            reviewer_actor_id=reviewer_actor_id,
            rationale=payload["rationale"],
            triggering_inputs_json=payload.get("triggering_inputs", []),
            **provenance,
        )
        session.add(revision)
        session.flush()
        return [revision.id]
    if item.command_type == "CreateQuestion":
        question = Question(
            namespace_id=proposal.namespace_id,
            wording=payload["wording"],
            importance_rationale=payload["importance_rationale"],
            tractability=payload.get("tractability", "unknown"),
            **provenance,
        )
        session.add(question)
        session.flush()
        return [question.id]
    raise DomainError("proposal.command_not_allowed", "Unsupported command")
