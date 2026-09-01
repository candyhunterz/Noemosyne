"""Build compact, deterministic, provenance-complete claim context bundles."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from noemosyne_db.models import (
    AssessmentInput,
    AssessmentPolicy,
    Challenge,
    Claim,
    ClaimVersion,
    EpistemicAssessment,
    EvidenceDependencyGroup,
    EvidenceItem,
    EvidenceItemSource,
    EvidenceLink,
    SourceArtifact,
    SourceFragment,
)
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session


def _historical_filter(model: Any, cutoff: datetime, domain_time: datetime) -> Any:
    return and_(
        model.status == "accepted",
        model.recorded_at <= cutoff,
        model.valid_from <= domain_time,
        or_(model.valid_to.is_(None), model.valid_to > domain_time),
    )


def build_context_bundle(
    session: Session,
    claim_id: str,
    knowledge_cutoff: datetime,
    domain_time: datetime,
    max_evidence_per_stance: int = 20,
    include_history_summary: bool = True,
    include_open_challenges: bool = True,
) -> dict[str, Any] | None:
    """Return claim state known at ``knowledge_cutoff`` without temporal leakage."""
    claim = session.scalar(
        select(Claim).where(
            Claim.id == claim_id,
            Claim.status == "accepted",
            Claim.recorded_at <= knowledge_cutoff,
        )
    )
    if claim is None:
        return None

    version = session.scalar(
        select(ClaimVersion)
        .where(
            ClaimVersion.claim_id == claim_id,
            _historical_filter(ClaimVersion, knowledge_cutoff, domain_time),
        )
        .order_by(ClaimVersion.recorded_at.desc(), ClaimVersion.version_number.desc())
        .limit(1)
    )
    assessment = session.scalar(
        select(EpistemicAssessment)
        .where(
            EpistemicAssessment.claim_id == claim_id,
            _historical_filter(EpistemicAssessment, knowledge_cutoff, domain_time),
        )
        .order_by(EpistemicAssessment.recorded_at.desc(), EpistemicAssessment.id)
        .limit(1)
    )

    evidence_rows = session.execute(
        select(EvidenceLink, EvidenceItem, EvidenceDependencyGroup)
        .join(EvidenceItem, EvidenceItem.id == EvidenceLink.evidence_item_id)
        .outerjoin(
            EvidenceDependencyGroup, EvidenceDependencyGroup.id == EvidenceLink.dependency_group_id
        )
        .where(
            EvidenceLink.claim_id == claim_id,
            _historical_filter(EvidenceLink, knowledge_cutoff, domain_time),
        )
        .order_by(
            EvidenceLink.stance,
            EvidenceLink.dependency_group_id,
            EvidenceLink.recorded_at,
            EvidenceLink.id,
        )
    ).all()

    stance_counts: dict[str, int] = {"supports": 0, "challenges": 0, "contextualizes": 0}
    omissions: dict[str, int] = {"supports": 0, "challenges": 0, "contextualizes": 0}
    grouped: dict[str, dict[str, Any]] = {}
    for link, item, group in evidence_rows:
        if stance_counts[link.stance] >= max_evidence_per_stance:
            omissions[link.stance] += 1
            continue
        stance_counts[link.stance] += 1
        group_key = group.id if group is not None else f"independent:{item.id}"
        group_data = grouped.setdefault(
            group_key,
            {
                "dependency_group": None
                if group is None
                else {
                    "id": group.id,
                    "label": group.label,
                    "dependency_type": group.dependency_type,
                },
                "items": [],
            },
        )
        source_rows = session.execute(
            select(SourceFragment, SourceArtifact)
            .join(EvidenceItemSource, EvidenceItemSource.source_fragment_id == SourceFragment.id)
            .join(SourceArtifact, SourceArtifact.id == SourceFragment.source_artifact_id)
            .where(EvidenceItemSource.evidence_item_id == item.id)
            .order_by(SourceArtifact.id, SourceFragment.id)
        ).all()
        group_data["items"].append(
            {
                "evidence_link_id": link.id,
                "evidence_item_id": item.id,
                "stance": link.stance,
                "directness": link.directness,
                "strength_band": link.strength_band,
                "scope_match": link.scope_match,
                "caveats": link.caveats_json,
                "evaluator_actor_id": link.evaluator_actor_id,
                "assessment_policy_id": link.assessment_policy_id,
                "sources": [
                    {
                        "source_id": source.id,
                        "title": source.title,
                        "uri": source.canonical_uri,
                        "license_basis": fragment.license_basis,
                        "fragment_id": fragment.id,
                        "locator": fragment.locator_json,
                    }
                    for fragment, source in source_rows
                ],
            }
        )

    assessment_data = None
    if assessment is not None:
        policy = session.get(AssessmentPolicy, assessment.policy_id)
        inputs = session.scalars(
            select(AssessmentInput)
            .where(
                AssessmentInput.assessment_id == assessment.id, AssessmentInput.status == "accepted"
            )
            .order_by(AssessmentInput.position, AssessmentInput.id)
        ).all()
        assessment_data = {
            "id": assessment.id,
            "verdict": assessment.verdict,
            "profile": {
                "directness": assessment.directness,
                "methodological_quality": assessment.methodological_quality,
                "independence": assessment.independence,
                "consistency": assessment.consistency,
                "scope_fit": assessment.scope_fit,
                "stability": assessment.stability,
            },
            "rationale": assessment.rationale,
            "uncertainty_drivers": assessment.uncertainty_drivers_json,
            "assessor_actor_id": assessment.assessor_actor_id,
            "policy": None
            if policy is None
            else {"id": policy.id, "name": policy.name, "version": policy.version},
            "input_ids": [item.input_id for item in inputs],
            "recorded_at": assessment.recorded_at,
        }

    challenges: list[dict[str, Any]] = []
    if include_open_challenges:
        rows = session.scalars(
            select(Challenge)
            .where(
                Challenge.target_id == claim_id,
                Challenge.status == "accepted",
                Challenge.resolution_status == "open",
                Challenge.recorded_at <= knowledge_cutoff,
            )
            .order_by(Challenge.recorded_at, Challenge.id)
        ).all()
        challenges = [
            {
                "id": row.id,
                "category": row.category,
                "explanation": row.explanation,
                "raised_by_actor_id": row.raised_by_actor_id,
            }
            for row in rows
        ]

    history_summary: dict[str, Any] | None = None
    if include_history_summary:
        history = session.scalars(
            select(EpistemicAssessment)
            .where(
                EpistemicAssessment.claim_id == claim_id,
                EpistemicAssessment.recorded_at <= knowledge_cutoff,
            )
            .order_by(EpistemicAssessment.recorded_at, EpistemicAssessment.id)
        ).all()
        history_summary = {
            "assessment_count": len(history),
            "verdict_sequence": [row.verdict for row in history],
        }

    return {
        "claim": None
        if version is None
        else {
            "id": claim.id,
            "version_id": version.id,
            "wording": version.wording,
            "scope": version.scope_json,
            "valid_from": version.valid_from,
            "recorded_at": version.recorded_at,
        },
        "assessment": assessment_data,
        "evidence_groups": list(grouped.values()),
        "open_challenges": challenges,
        "history_summary": history_summary,
        "query": {"knowledge_cutoff": knowledge_cutoff, "domain_time": domain_time},
        "omissions": {key: value for key, value in omissions.items() if value},
    }
