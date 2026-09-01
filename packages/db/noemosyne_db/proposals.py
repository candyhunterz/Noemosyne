"""Transactional proposal validation, review, and canonical application."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from noemosyne_domain.errors import ConflictError, DomainError, NotFoundError
from noemosyne_domain.models import EvidenceLink as DomainEvidenceLink
from noemosyne_domain.models import (
    EvidenceStance,
    Verdict,
    validate_assessment_inputs,
    validate_relation,
)
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .models import (
    Argument,
    ArgumentPremise,
    Assertion,
    AssessmentInput,
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
    elif command_type == "AddSourceFragment":
        if not isinstance(payload["locator_json"], dict) or not payload["locator_json"]:
            raise DomainError("source.locator_required", "A source fragment requires a locator")
        if payload.get("stored_text") is not None and payload.get("text_hash") is None:
            expected = sha256(str(payload["stored_text"]).encode()).hexdigest()
            payload["text_hash"] = expected
    elif command_type == "CreateEvidenceItem":
        if payload["kind"] not in {"source_fragment", "argument"}:
            raise DomainError("evidence.invalid_kind", "M1 evidence is source_fragment or argument")
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
    all_valid = True
    for item in items:
        try:
            validate_command(item.command_type, item.payload_json)
            _validate_precondition_shape(item.preconditions_json)
            item.status = "valid"
            item.validation_errors_json = []
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
    proposal = session.get(Proposal, proposal_id)
    item = session.get(ProposalItem, item_id)
    if proposal is None or item is None or item.proposal_id != proposal.id:
        raise NotFoundError("proposal.item_not_found", "Proposal item not found")
    if proposal.status != "in_review":
        raise ConflictError("proposal.not_in_review", "Proposal is not open for review")
    if reviewer_actor_id == proposal.proposer_actor_id:
        raise DomainError(
            "review.separation_of_duty", "A proposer cannot review their own proposal"
        )
    review = ReviewDecision(
        proposal_item_id=item.id,
        reviewer_actor_id=reviewer_actor_id,
        decision=decision,
        rationale=rationale,
    )
    session.add(review)
    session.commit()
    return review


def _latest_decision(session: Session, item_id: str) -> ReviewDecision | None:
    return session.scalar(
        select(ReviewDecision)
        .where(ReviewDecision.proposal_item_id == item_id)
        .order_by(ReviewDecision.recorded_at.desc(), ReviewDecision.id.desc())
        .limit(1)
    )


def apply_proposal(session: Session, proposal_id: str, applied_by_actor_id: str) -> Proposal:
    """Apply all review-accepted items atomically and idempotently."""
    try:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(text("SET LOCAL noemosyne.accepting_proposal = 'on'"))
        proposal = session.scalar(
            select(Proposal).where(Proposal.id == proposal_id).with_for_update()
        )
        if proposal is None:
            raise NotFoundError("proposal.not_found", "Proposal not found")
        if proposal.status in {"accepted", "partially_accepted"}:
            return proposal
        if proposal.status != "in_review":
            raise ConflictError("proposal.not_in_review", "Proposal must be submitted before apply")
        namespace = session.scalar(
            select(Namespace).where(Namespace.id == proposal.namespace_id).with_for_update()
        )
        if namespace is None:
            raise NotFoundError("namespace.not_found", "Namespace not found")
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
        accepted: list[tuple[ProposalItem, ReviewDecision]] = []
        for item in items:
            decision = _latest_decision(session, item.id)
            if decision is None:
                raise DomainError("review.required", "Every proposal item needs a review decision")
            if decision.reviewer_actor_id == proposal.proposer_actor_id:
                raise DomainError(
                    "review.separation_of_duty", "A proposer cannot accept their own item"
                )
            if decision.decision == "accept":
                accepted.append((item, decision))
            else:
                item.status = "rejected"
        if not accepted:
            proposal.status = "rejected"
            proposal.applied_at = datetime.now(UTC)
            proposal.applied_by_actor_id = applied_by_actor_id
            session.commit()
            return proposal
        for item, decision in accepted:
            validate_command(item.command_type, item.payload_json)
            _verify_preconditions(session, item)
            created_ids = _execute_command(
                session,
                proposal,
                item,
                decision.reviewer_actor_id,
            )
            item.created_canonical_ids_json = created_ids
            item.status = "accepted"
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
            stale_proposal = session.get(Proposal, proposal_id)
            if stale_proposal is not None and stale_proposal.status == "in_review":
                stale_proposal.status = "stale"
                stale_items = session.scalars(
                    select(ProposalItem).where(ProposalItem.proposal_id == proposal_id)
                ).all()
                for stale_item in stale_items:
                    stale_item.status = "stale"
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
            **provenance,
        )
        session.add(version)
        session.flush()
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
        return [assessment.id]
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
