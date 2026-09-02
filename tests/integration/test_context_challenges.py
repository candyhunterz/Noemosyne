from datetime import UTC, datetime, timedelta

from noemosyne_db.models import (
    Actor,
    Challenge,
    Claim,
    ClaimVersion,
    Namespace,
    Proposal,
    ProposalItem,
    ReviewDecision,
    SourceArtifact,
)
from noemosyne_retrieval.context_bundle import build_context_bundle


def test_claim_context_filters_polymorphic_challenges_by_type_and_namespace(session) -> None:
    namespace = Namespace(slug="challenge-context", name="Challenge context")
    other_namespace = Namespace(slug="challenge-context-other", name="Other challenge context")
    session.add_all([namespace, other_namespace])
    session.flush()
    proposer = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="Challenge proposer",
        external_id="challenge-proposer",
    )
    reviewer = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="Challenge reviewer",
        external_id="challenge-reviewer",
    )
    other_proposer = Actor(
        namespace_id=other_namespace.id,
        kind="human",
        display_name="Other proposer",
        external_id="other-challenge-proposer",
    )
    other_reviewer = Actor(
        namespace_id=other_namespace.id,
        kind="human",
        display_name="Other reviewer",
        external_id="other-challenge-reviewer",
    )
    session.add_all([proposer, reviewer, other_proposer, other_reviewer])
    session.flush()

    def accepted_item(proposal_namespace, author, approver, position: int) -> ProposalItem:
        proposal = Proposal(
            namespace_id=proposal_namespace.id,
            proposer_actor_id=author.id,
            title=f"Challenge provenance {position}",
            base_revision_token=0,
            status="accepted",
            submitted_at=datetime.now(UTC),
            applied_at=datetime.now(UTC),
            applied_by_actor_id=approver.id,
        )
        session.add(proposal)
        session.flush()
        item = ProposalItem(
            proposal_id=proposal.id,
            position=0,
            command_type="RaiseChallenge",
            payload_json={},
            status="accepted",
        )
        session.add(item)
        session.flush()
        session.add(
            ReviewDecision(
                proposal_item_id=item.id,
                reviewer_actor_id=approver.id,
                decision="accept",
                rationale="Accepted challenge fixture",
            )
        )
        return item

    item = accepted_item(namespace, proposer, reviewer, 0)
    other_item = accepted_item(other_namespace, other_proposer, other_reviewer, 1)
    shared_id = "40000000-0000-0000-0000-000000000001"
    version_id = "40000000-0000-0000-0000-000000000002"
    claim = Claim(
        id=shared_id,
        namespace_id=namespace.id,
        current_version_id=version_id,
        status="accepted",
        proposal_item_id=item.id,
    )
    version = ClaimVersion(
        id=version_id,
        claim_id=shared_id,
        version_number=1,
        wording="A claim sharing its UUID with a source artifact.",
        scope_json={},
        valid_from=datetime(2025, 1, 1, tzinfo=UTC),
        status="accepted",
        proposal_item_id=item.id,
    )
    source = SourceArtifact(
        id=shared_id,
        namespace_id=namespace.id,
        kind="paper",
        title="Source with colliding UUID",
        canonical_uri="https://example.test/colliding-source",
        license_basis="metadata-only",
        status="accepted",
        proposal_item_id=item.id,
    )
    session.add_all([claim, version, source])
    session.flush()
    session.add_all(
        [
            Challenge(
                namespace_id=namespace.id,
                target_type="claim",
                target_id=shared_id,
                category="scope",
                explanation="Claim-targeted challenge",
                raised_by_actor_id=reviewer.id,
                status="accepted",
                proposal_item_id=item.id,
            ),
            Challenge(
                namespace_id=namespace.id,
                target_type="source_artifact",
                target_id=shared_id,
                category="source_quality",
                explanation="Source-targeted challenge",
                raised_by_actor_id=reviewer.id,
                status="accepted",
                proposal_item_id=item.id,
            ),
            Challenge(
                namespace_id=other_namespace.id,
                target_type="claim",
                target_id=shared_id,
                category="scope",
                explanation="Cross-namespace provenance challenge",
                raised_by_actor_id=other_reviewer.id,
                status="accepted",
                proposal_item_id=other_item.id,
            ),
        ]
    )
    session.commit()

    bundle = build_context_bundle(
        session,
        shared_id,
        datetime.now(UTC) + timedelta(seconds=1),
        datetime(2025, 2, 1, tzinfo=UTC),
    )

    assert bundle is not None
    assert [challenge["explanation"] for challenge in bundle["open_challenges"]] == [
        "Claim-targeted challenge"
    ]
