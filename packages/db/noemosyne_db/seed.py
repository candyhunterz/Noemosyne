"""Deterministic, idempotent seed import with proposal/review/audit provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Actor,
    AssessmentInput,
    AssessmentPolicy,
    AuditEvent,
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
    QuestionClaim,
    ReviewDecision,
    RevisionEvent,
    SourceArtifact,
    SourceFragment,
)
from .session import SessionLocal


class SeedPackage(BaseModel):
    """Versioned import envelope; nested records remain explicit dictionaries."""

    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(ge=1, le=1)
    package_id: str
    package_version: str
    namespace: dict[str, Any]
    actors: list[dict[str, Any]]
    policy: dict[str, Any]
    sources: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    dependency_groups: list[dict[str, Any]]
    assessments: list[dict[str, Any]]
    relations: list[dict[str, Any]]
    questions: list[dict[str, Any]]


def stable_id(package_id: str, kind: str, symbol: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{package_id}:{kind}:{symbol}"))


def parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def canonical_hash(raw: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(raw, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def export_seed(session: Session, identity: str, path: Path) -> dict[str, Any]:
    """Export the validated package envelope associated with an accepted seed audit."""
    event = session.scalar(
        select(AuditEvent).where(
            AuditEvent.event_type == "seed.imported",
            AuditEvent.object_id == identity,
        )
    )
    if event is None:
        raise ValueError(f"seed package {identity!r} has not been imported")
    payload = event.detail_json.get("package_payload")
    if not isinstance(payload, dict):
        raise ValueError("seed audit predates round-trip payload support")
    SeedPackage.model_validate(payload)
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    return {
        "status": "exported",
        "identity": identity,
        "sha256": event.detail_json["sha256"],
        "path": str(path),
    }


def import_seed(session: Session, path: Path) -> dict[str, Any]:
    """Import one package transactionally, returning a stable result report."""
    raw = yaml.safe_load(path.read_text())
    package = SeedPackage.model_validate(raw)
    digest = canonical_hash(raw)
    json_payload = json.loads(json.dumps(raw, default=str))
    previous = session.scalar(
        select(AuditEvent).where(
            AuditEvent.event_type == "seed.imported",
            AuditEvent.object_id == f"{package.package_id}@{package.package_version}",
        )
    )
    if previous is not None:
        if previous.detail_json.get("sha256") != digest:
            raise ValueError("seed package ID/version already exists with a different hash")
        return {
            "status": "noop",
            "package_id": package.package_id,
            "version": package.package_version,
            "sha256": digest,
        }

    ids: dict[str, str] = {}

    def sid(kind: str, symbol: str) -> str:
        value = stable_id(package.package_id, kind, symbol)
        ids[symbol] = value
        return value

    namespace_id = sid("namespace", package.namespace["symbol"])
    curator_id = sid("actor", package.actors[0]["symbol"])
    reviewer_id = sid("actor", package.actors[1]["symbol"])
    proposal_id = sid("proposal", f"{package.package_version}:{digest}")
    item_id = sid("proposal-item", "seed-import")
    try:
        namespace = Namespace(
            id=namespace_id,
            slug=package.namespace["symbol"],
            name=package.namespace["name"],
            revision_token=1,
        )
        session.add(namespace)
        session.flush()
        for actor_data in package.actors:
            actor_id = sid("actor", actor_data["symbol"])
            session.add(
                Actor(
                    id=actor_id,
                    namespace_id=namespace_id,
                    kind=actor_data["kind"],
                    display_name=actor_data["display_name"],
                    external_id=f"seed:{actor_data['symbol']}",
                    provenance_json={"package_id": package.package_id, "sha256": digest},
                )
            )
        session.flush()
        proposal = Proposal(
            id=proposal_id,
            namespace_id=namespace_id,
            proposer_actor_id=curator_id,
            title=f"Import {package.package_id} {package.package_version}",
            description="Deterministic illustrative seed import",
            base_revision_token=0,
            status="in_review",
            submitted_at=datetime.now(UTC),
        )
        session.add(proposal)
        session.flush()
        item = ProposalItem(
            id=item_id,
            proposal_id=proposal_id,
            position=0,
            command_type="ImportSeedPackage",
            payload_json={
                "package_id": package.package_id,
                "version": package.package_version,
                "sha256": digest,
            },
            status="valid",
        )
        session.add(item)
        session.flush()
        session.add(
            ReviewDecision(
                proposal_item_id=item_id,
                reviewer_actor_id=reviewer_id,
                decision="accept",
                rationale="Reviewed illustrative locators and scope-qualified annotations",
            )
        )
        session.flush()
        item.status = "accepted"
        session.flush()
        proposal.status = "accepted"
        proposal.applied_at = datetime.now(UTC)
        proposal.applied_by_actor_id = reviewer_id
        session.flush()
        policy_id = sid("policy", package.policy["symbol"])
        session.add(
            AssessmentPolicy(
                id=policy_id,
                namespace_id=namespace_id,
                name=package.policy["name"],
                version=package.policy["version"],
                rules_json={
                    "aggregation": "reasoned ordinal profile",
                    "numeric_truth_score": False,
                },
                status="accepted",
                proposal_item_id=item_id,
            )
        )
        session.flush()

        for source_data in package.sources:
            source_id = sid("source", source_data["symbol"])
            session.add(
                SourceArtifact(
                    id=source_id,
                    namespace_id=namespace_id,
                    kind=source_data["kind"],
                    title=source_data["title"],
                    canonical_uri=source_data["canonical_uri"],
                    license_basis=source_data["license_basis"],
                    access_json=source_data.get("access", {}),
                    status="accepted",
                    proposal_item_id=item_id,
                )
            )
            session.flush()
            for fragment_data in source_data["fragments"]:
                fragment_id = sid("fragment", fragment_data["symbol"])
                session.add(
                    SourceFragment(
                        id=fragment_id,
                        source_artifact_id=source_id,
                        locator_json=fragment_data["locator"],
                        license_basis=fragment_data["license_basis"],
                        status="accepted",
                        proposal_item_id=item_id,
                    )
                )

        for claim_data in package.claims:
            claim_id = sid("claim", claim_data["symbol"])
            version_id = sid("claim-version", f"{claim_data['symbol']}:1")
            session.add(
                Claim(
                    id=claim_id,
                    namespace_id=namespace_id,
                    current_version_id=version_id,
                    status="accepted",
                    proposal_item_id=item_id,
                )
            )
            session.flush()
            session.add(
                ClaimVersion(
                    id=version_id,
                    claim_id=claim_id,
                    version_number=1,
                    wording=claim_data["wording"],
                    scope_json=claim_data["scope"],
                    valid_from=parse_time(claim_data["valid_from"]),
                    status="accepted",
                    proposal_item_id=item_id,
                )
            )

        for group_data in package.dependency_groups:
            group_id = sid("dependency-group", group_data["symbol"])
            session.add(
                EvidenceDependencyGroup(
                    id=group_id,
                    namespace_id=namespace_id,
                    label=group_data["label"],
                    dependency_type=group_data["dependency_type"],
                    status="accepted",
                    proposal_item_id=item_id,
                )
            )
        session.flush()

        link_ids: dict[str, str] = {}
        for evidence_data in package.evidence:
            evidence_id = sid("evidence-item", evidence_data["symbol"])
            link_id = stable_id(package.package_id, "evidence-link", evidence_data["symbol"])
            link_ids[evidence_data["symbol"]] = link_id
            session.add(
                EvidenceItem(
                    id=evidence_id,
                    namespace_id=namespace_id,
                    kind="source_fragment",
                    description=f"Seed evidence: {evidence_data['symbol']}",
                    status="accepted",
                    proposal_item_id=item_id,
                )
            )
            session.flush()
            session.add(
                EvidenceItemSource(
                    evidence_item_id=evidence_id,
                    source_fragment_id=ids[evidence_data["fragment"]],
                    status="accepted",
                    proposal_item_id=item_id,
                )
            )
            session.flush()
            group_id = ids[evidence_data["dependency_group"]]
            session.add(
                EvidenceDependencyMember(
                    dependency_group_id=group_id,
                    evidence_item_id=evidence_id,
                    status="accepted",
                    proposal_item_id=item_id,
                )
            )
            session.add(
                EvidenceLink(
                    id=link_id,
                    claim_id=ids[evidence_data["claim"]],
                    evidence_item_id=evidence_id,
                    evaluator_actor_id=curator_id,
                    assessment_policy_id=policy_id,
                    dependency_group_id=group_id,
                    stance=evidence_data["stance"],
                    directness=evidence_data["directness"],
                    strength_band=evidence_data["strength_band"],
                    scope_match=evidence_data["scope_match"],
                    valid_from=datetime(2023, 1, 1, tzinfo=UTC),
                    status="accepted",
                    proposal_item_id=item_id,
                )
            )

        for assessment_data in package.assessments:
            assessment_id = sid("assessment", assessment_data["symbol"])
            session.add(
                EpistemicAssessment(
                    id=assessment_id,
                    claim_id=ids[assessment_data["claim"]],
                    assessor_actor_id=curator_id,
                    policy_id=policy_id,
                    verdict=assessment_data["verdict"],
                    directness=assessment_data["directness"],
                    methodological_quality=assessment_data["methodological_quality"],
                    independence=assessment_data["independence"],
                    consistency=assessment_data["consistency"],
                    scope_fit=assessment_data["scope_fit"],
                    stability=assessment_data["stability"],
                    rationale=assessment_data["rationale"],
                    uncertainty_drivers_json=assessment_data["uncertainty_drivers"],
                    valid_from=parse_time(assessment_data["valid_from"]),
                    status="accepted",
                    proposal_item_id=item_id,
                )
            )
            # Explicit because mappings intentionally avoid ORM relationships;
            # PostgreSQL must see the parent before its generic input references.
            session.flush()
            for position, evidence_symbol in enumerate(assessment_data["inputs"]):
                session.add(
                    AssessmentInput(
                        assessment_id=assessment_id,
                        input_type="evidence_link",
                        input_id=link_ids[evidence_symbol],
                        position=position,
                        status="accepted",
                        proposal_item_id=item_id,
                    )
                )
            revision_id = sid("revision", f"initial:{assessment_data['symbol']}")
            session.add(
                RevisionEvent(
                    id=revision_id,
                    claim_id=ids[assessment_data["claim"]],
                    before_assessment_id=None,
                    after_assessment_id=assessment_id,
                    author_actor_id=curator_id,
                    reviewer_actor_id=reviewer_id,
                    rationale="Initial assessment imported with deterministic seed",
                    status="accepted",
                    proposal_item_id=item_id,
                )
            )

        for relation_data in package.relations:
            session.add(
                ClaimRelation(
                    id=sid(
                        "relation",
                        f"{relation_data['source']}:{relation_data['type']}:{relation_data['target']}",
                    ),
                    source_claim_id=ids[relation_data["source"]],
                    target_claim_id=ids[relation_data["target"]],
                    relation_type=relation_data["type"],
                    context_json=relation_data["context"],
                    reviewer_actor_id=reviewer_id,
                    status="accepted",
                    proposal_item_id=item_id,
                )
            )

        for question_data in package.questions:
            question_id = sid("question", question_data["symbol"])
            session.add(
                Question(
                    id=question_id,
                    namespace_id=namespace_id,
                    wording=question_data["wording"],
                    importance_rationale=question_data["importance_rationale"],
                    status="accepted",
                    proposal_item_id=item_id,
                )
            )
            session.flush()
            for claim_symbol in question_data["candidate_claims"]:
                session.add(
                    QuestionClaim(
                        question_id=question_id,
                        claim_id=ids[claim_symbol],
                        role="candidate_answer",
                        status="accepted",
                        proposal_item_id=item_id,
                    )
                )

        session.add(
            AuditEvent(
                namespace_id=namespace_id,
                actor_id=reviewer_id,
                event_type="seed.imported",
                object_type="seed_package",
                object_id=f"{package.package_id}@{package.package_version}",
                proposal_id=proposal_id,
                detail_json={
                    "sha256": digest,
                    "path": str(path),
                    "symbol_ids": ids,
                    "package_payload": json_payload,
                },
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {
        "status": "imported",
        "package_id": package.package_id,
        "version": package.package_version,
        "sha256": digest,
        "namespace_id": namespace_id,
        "symbol_ids": ids,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["import", "export"])
    parser.add_argument("subject")
    parser.add_argument("output", nargs="?", type=Path)
    args = parser.parse_args()
    with SessionLocal() as session:
        if args.command == "import":
            result = import_seed(session, Path(args.subject))
        else:
            if args.output is None:
                parser.error("export requires an output path")
            result = export_seed(session, args.subject, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
