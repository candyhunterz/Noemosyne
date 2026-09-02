from datetime import UTC, datetime, timedelta

from noemosyne_db.models import (
    Actor,
    Argument,
    ArgumentPremise,
    AssessmentPolicy,
    Claim,
    ClaimVersion,
    EvidenceItem,
    EvidenceItemSource,
    EvidenceLink,
    Namespace,
    SourceArtifact,
    SourceFragment,
)
from noemosyne_retrieval.context_bundle import build_context_bundle


def test_context_omits_every_invalid_provenance_shape_and_returns_valid_content(session) -> None:
    namespace = Namespace(slug="context-provenance", name="Context provenance")
    other_namespace = Namespace(slug="context-other", name="Context other")
    session.add_all([namespace, other_namespace])
    session.flush()
    actor = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="Evaluator",
        external_id="context-evaluator",
    )
    policy = AssessmentPolicy(
        namespace_id=namespace.id,
        name="Context policy",
        version="1",
        status="accepted",
    )
    session.add_all([actor, policy])
    session.flush()
    claim_id = "30000000-0000-0000-0000-000000000001"
    version_id = "30000000-0000-0000-0000-000000000002"
    claim = Claim(
        id=claim_id,
        namespace_id=namespace.id,
        current_version_id=version_id,
        status="accepted",
    )
    version = ClaimVersion(
        id=version_id,
        claim_id=claim_id,
        version_number=1,
        wording="Context provenance claim",
        scope_json={},
        valid_from=datetime(2025, 1, 1, tzinfo=UTC),
        status="accepted",
    )
    session.add_all([claim, version])
    session.flush()

    valid_source = SourceArtifact(
        namespace_id=namespace.id,
        kind="paper",
        title="Valid source",
        canonical_uri="https://example.test/valid-context",
        license_basis="metadata-only",
        status="accepted",
    )
    incomplete_source = SourceArtifact(
        namespace_id=namespace.id,
        kind="paper",
        title="",
        canonical_uri="",
        license_basis="",
        status="accepted",
    )
    cross_source = SourceArtifact(
        namespace_id=other_namespace.id,
        kind="paper",
        title="Other source",
        canonical_uri="https://example.test/other-context",
        license_basis="metadata-only",
        status="accepted",
    )
    session.add_all([valid_source, incomplete_source, cross_source])
    session.flush()
    valid_fragment = SourceFragment(
        source_artifact_id=valid_source.id,
        locator_json={"section": "valid"},
        license_basis="locator-only",
        status="accepted",
    )
    incomplete_fragment = SourceFragment(
        source_artifact_id=incomplete_source.id,
        locator_json={"section": "incomplete"},
        license_basis="locator-only",
        status="accepted",
    )
    cross_fragment = SourceFragment(
        source_artifact_id=cross_source.id,
        locator_json={"section": "cross"},
        license_basis="locator-only",
        status="accepted",
    )
    session.add_all([valid_fragment, incomplete_fragment, cross_fragment])
    session.flush()

    argument = Argument(
        namespace_id=namespace.id,
        conclusion_claim_id=claim.id,
        author_actor_id=actor.id,
        inference_scheme="deductive",
        rationale="Valid explicit reasoning",
        status="accepted",
    )
    session.add(argument)
    session.flush()
    session.add(
        ArgumentPremise(
            argument_id=argument.id,
            premise_type="claim",
            premise_id=claim.id,
            position=0,
            status="accepted",
        )
    )

    cases = [
        EvidenceItem(namespace_id=namespace.id, kind="source_fragment", status="accepted"),
        EvidenceItem(namespace_id=namespace.id, kind="argument", status="accepted"),
        EvidenceItem(namespace_id=namespace.id, kind="source_fragment", status="accepted"),
        EvidenceItem(namespace_id=namespace.id, kind="source_fragment", status="accepted"),
        EvidenceItem(namespace_id=namespace.id, kind="source_fragment", status="accepted"),
        EvidenceItem(
            namespace_id=namespace.id,
            kind="argument",
            argument_id=argument.id,
            status="accepted",
        ),
    ]
    session.add_all(cases)
    session.flush()
    for item, fragment in (
        (cases[2], cross_fragment),
        (cases[3], incomplete_fragment),
        (cases[4], valid_fragment),
    ):
        session.add(
            EvidenceItemSource(
                evidence_item_id=item.id,
                source_fragment_id=fragment.id,
                status="accepted",
            )
        )
    for item in cases:
        session.add(
            EvidenceLink(
                claim_id=claim.id,
                evidence_item_id=item.id,
                evaluator_actor_id=actor.id,
                assessment_policy_id=policy.id,
                stance="supports",
                directness="direct",
                strength_band="material",
                scope_match="Fixture scope",
                valid_from=datetime(2025, 1, 1, tzinfo=UTC),
                status="accepted",
            )
        )
    session.commit()

    bundle = build_context_bundle(
        session,
        claim.id,
        datetime.now(UTC) + timedelta(seconds=1),
        datetime.now(UTC),
    )
    assert bundle is not None
    returned = [item for group in bundle["evidence_groups"] for item in group["items"]]
    assert len(returned) == 2
    assert any(item["sources"] for item in returned)
    assert any(item["argument"] is not None for item in returned)
    assert bundle["omissions"]["invalid_provenance"] == 4
