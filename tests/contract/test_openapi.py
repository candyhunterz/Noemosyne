from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from noemosyne_api.dependencies import get_session
from noemosyne_api.main import app
from noemosyne_api.schemas import (
    ActivityResponse,
    ActorListResponse,
    ClaimHistoryResponse,
    ClaimResponse,
    ContextBundleResponse,
    GraphTraceResponse,
    HealthResponse,
    NamespaceResponse,
    ProblemDetail,
    ProposalListResponse,
    ProposalResponse,
    SearchResponse,
    SourceResponse,
)


@pytest.mark.asyncio
async def test_versioned_openapi_has_explicit_success_and_problem_schemas() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/health/live")
        assert response.status_code == 200
        assert HealthResponse.model_validate(response.json()).status == "ok"
        schema = (await client.get("/v1/openapi.json")).json()

    assert schema["info"]["title"] == "Noemosyne API"
    required = {
        "/v1/claims/{claim_id}/context",
        "/v1/claims/{claim_id}/history",
        "/v1/claims:search",
        "/v1/graph:trace",
        "/v1/proposals/{proposal_id}:apply",
    }
    assert required <= schema["paths"].keys()
    for path_item in schema["paths"].values():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            success = operation["responses"].get("200") or operation["responses"].get("201")
            assert success is not None
            success_schema = success["content"]["application/json"]["schema"]
            assert "$ref" in success_schema
            for status in ("400", "404", "409", "422"):
                problem_content = operation["responses"][status]["content"]
                assert "application/problem+json" in problem_content
                problem_schema = problem_content["application/problem+json"]["schema"]
                assert problem_schema["$ref"].endswith("/ProblemDetail")


def test_committed_openapi_is_synchronized_and_source_text_is_not_public() -> None:
    committed = json.loads(Path("openapi.json").read_text())
    assert committed == app.openapi()
    source_contract = json.dumps(committed["components"]["schemas"]["SourceResponse"])
    assert "stored_text" not in source_contract
    assert "SourceFragmentResponse" in source_contract


@pytest.mark.asyncio
async def test_all_public_read_success_payloads_validate_explicit_models(session) -> None:
    from noemosyne_db.models import Proposal, ProposalItem, SourceFragment
    from noemosyne_db.seed import import_seed

    report = import_seed(session, Path("examples/ai-research/seed.yaml"))
    ids = report["symbol_ids"]
    stored_fragment = session.get(SourceFragment, ids["snell-efficiency"])
    assert stored_fragment is not None
    stored_fragment.stored_text = "licensed internal fixture text that must not leak"
    stored_fragment.text_hash = "contract-fixture-hash"
    text_proposal = Proposal(
        namespace_id=report["namespace_id"],
        proposer_actor_id=ids["curator"],
        title="Stored-text disclosure fixture",
        base_revision_token=1,
    )
    session.add(text_proposal)
    session.flush()
    session.add(
        ProposalItem(
            proposal_id=text_proposal.id,
            position=0,
            command_type="AddSourceFragment",
            payload_json={
                "source_artifact_id": ids["snell-2024"],
                "locator_json": {"section": "private fixture"},
                "license_basis": "test-only",
                "stored_text": "proposal payload secret that must not leak",
                "text_hash": "proposal-fixture-hash",
            },
        )
    )
    session.commit()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            ready = await client.get("/v1/health/ready")
            assert HealthResponse.model_validate(ready.json()).status == "ready"
            namespace = await client.get(f"/v1/namespaces/{report['namespace_id']}")
            NamespaceResponse.model_validate(namespace.json())
            actors = await client.get(f"/v1/namespaces/{report['namespace_id']}/actors")
            ActorListResponse.model_validate(actors.json())
            claim = await client.get(f"/v1/claims/{ids['inference-time']}")
            ClaimResponse.model_validate(claim.json())
            context = await client.get(f"/v1/claims/{ids['inference-time']}/context")
            ContextBundleResponse.model_validate(context.json())
            history = await client.get(f"/v1/claims/{ids['inference-time']}/history")
            ClaimHistoryResponse.model_validate(history.json())
            search = await client.post(
                "/v1/claims:search",
                json={
                    "namespace_id": report["namespace_id"],
                    "query": "inference-time",
                    "limit": 20,
                    "verdicts": [],
                },
            )
            SearchResponse.model_validate(search.json())
            graph = await client.post(
                "/v1/graph:trace",
                json={
                    "start_claim_id": ids["memory-capacity"],
                    "relation_types": ["incompatible_with"],
                    "max_depth": 3,
                    "max_nodes": 100,
                },
            )
            GraphTraceResponse.model_validate(graph.json())
            source = await client.get(f"/v1/sources/{ids['snell-2024']}")
            source_payload = SourceResponse.model_validate(source.json())
            assert "stored_text" not in source.text
            assert "licensed internal fixture text" not in source.text
            assert source_payload.fragments
            activity = await client.get(f"/v1/activity?namespace_id={report['namespace_id']}")
            ActivityResponse.model_validate(activity.json())
            proposals = await client.get("/v1/proposals")
            proposal_list = ProposalListResponse.model_validate(proposals.json())
            assert proposal_list.proposals
            proposal = await client.get(f"/v1/proposals/{proposal_list.proposals[0].id}")
            ProposalResponse.model_validate(proposal.json())
            text_proposal_response = await client.get(f"/v1/proposals/{text_proposal.id}")
            assert "proposal payload secret" not in text_proposal_response.text
            assert (
                text_proposal_response.json()["items"][0]["payload"]["stored_text_present"] is True
            )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_http_proposal_lifecycle_and_rfc9457_errors(session) -> None:
    from noemosyne_db.models import Actor, AuditEvent, Claim, Namespace

    namespace = Namespace(slug="http-contract", name="HTTP contract")
    session.add(namespace)
    session.flush()
    proposer = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="HTTP proposer",
        external_id="http-p",
    )
    reviewer = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="HTTP reviewer",
        external_id="http-r",
    )
    retry_actor = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="HTTP retry actor",
        external_id="http-retry",
    )
    session.add_all([proposer, reviewer, retry_actor])
    session.commit()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/v1/proposals",
                json={
                    "namespace_id": namespace.id,
                    "proposer_actor_id": proposer.id,
                    "title": "HTTP candidate",
                    "description": "Contract workflow",
                    "base_revision_token": 0,
                },
            )
            assert created.status_code == 201
            proposal = ProposalResponse.model_validate(created.json())
            added = await client.post(
                f"/v1/proposals/{proposal.id}/items",
                json={
                    "command_type": "CreateClaim",
                    "payload": {
                        "wording": "A claim created through the HTTP workflow.",
                        "scope_json": {"fixture": "contract"},
                        "valid_from": "2025-01-01T00:00:00Z",
                    },
                    "preconditions": {},
                },
            )
            proposal = ProposalResponse.model_validate(added.json())
            validated = await client.post(f"/v1/proposals/{proposal.id}:validate")
            assert ProposalResponse.model_validate(validated.json()).status == "ready"
            submitted = await client.post(f"/v1/proposals/{proposal.id}:submit")
            proposal = ProposalResponse.model_validate(submitted.json())
            reviewed = await client.post(
                f"/v1/proposals/{proposal.id}/reviews",
                json={
                    "proposal_item_id": proposal.items[0].id,
                    "reviewer_actor_id": reviewer.id,
                    "decision": "accept",
                    "rationale": "The claim is narrow and inspectable",
                },
            )
            proposal = ProposalResponse.model_validate(reviewed.json())
            assert proposal.items[0].effective_outcome == "accept"
            applied = await client.post(
                f"/v1/proposals/{proposal.id}:apply",
                json={"applied_by_actor_id": reviewer.id},
            )
            proposal = ProposalResponse.model_validate(applied.json())
            assert proposal.status == "accepted"
            assert proposal.items[0].created_canonical_ids
            accepted_snapshot = (
                proposal.applied_at,
                proposal.applied_by_actor_id,
                tuple(proposal.items[0].created_canonical_ids),
                namespace.revision_token,
                session.query(Claim).count(),
                session.query(AuditEvent).count(),
            )

            # The first success could have reached the server while its response was lost.
            ambiguous_retry = await client.post(
                f"/v1/proposals/{proposal.id}:apply",
                json={"applied_by_actor_id": retry_actor.id},
            )
            retried = ProposalResponse.model_validate(ambiguous_retry.json())
            assert ambiguous_retry.status_code == 200
            assert (
                retried.applied_at,
                retried.applied_by_actor_id,
                tuple(retried.items[0].created_canonical_ids),
                namespace.revision_token,
                session.query(Claim).count(),
                session.query(AuditEvent).count(),
            ) == accepted_snapshot

            missing = await client.get("/v1/claims/not-a-claim")
            assert missing.status_code == 404
            missing_problem = ProblemDetail.model_validate(missing.json())
            assert missing_problem.status == 404
            assert missing_problem.code == "claim.not_found"
            assert missing.headers["content-type"].startswith("application/problem+json")

            invalid = await client.post("/v1/proposals", json={})
            assert invalid.status_code == 422
            invalid_problem = ProblemDetail.model_validate(invalid.json())
            assert invalid_problem.status == 422
            assert invalid_problem.code == "request.validation_failed"
            assert invalid.headers["content-type"].startswith("application/problem+json")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_http_partial_rejected_and_stale_apply_retries_are_stable(session) -> None:
    from noemosyne_db.models import Actor, AuditEvent, Claim, Namespace

    namespace = Namespace(slug="http-idempotence", name="HTTP idempotence")
    session.add(namespace)
    session.flush()
    proposer = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="HTTP idempotence proposer",
        external_id="http-idempotence-p",
    )
    reviewer = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="HTTP idempotence reviewer",
        external_id="http-idempotence-r",
    )
    retry_actor = Actor(
        namespace_id=namespace.id,
        kind="human",
        display_name="HTTP idempotence retry actor",
        external_id="http-idempotence-retry",
    )
    session.add_all([proposer, reviewer, retry_actor])
    session.commit()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

            async def prepare(decisions: list[str], title: str) -> ProposalResponse:
                created = await client.post(
                    "/v1/proposals",
                    json={
                        "namespace_id": namespace.id,
                        "proposer_actor_id": proposer.id,
                        "title": title,
                        "description": "HTTP retry regression",
                        "base_revision_token": namespace.revision_token,
                    },
                )
                proposal = ProposalResponse.model_validate(created.json())
                for position in range(len(decisions)):
                    added = await client.post(
                        f"/v1/proposals/{proposal.id}/items",
                        json={
                            "command_type": "CreateClaim",
                            "payload": {
                                "wording": f"HTTP retry claim {title} {position}.",
                                "scope_json": {"position": position},
                                "valid_from": "2025-01-01T00:00:00Z",
                            },
                            "preconditions": {},
                        },
                    )
                    proposal = ProposalResponse.model_validate(added.json())
                await client.post(f"/v1/proposals/{proposal.id}:validate")
                submitted = await client.post(f"/v1/proposals/{proposal.id}:submit")
                proposal = ProposalResponse.model_validate(submitted.json())
                for item, decision in zip(proposal.items, decisions, strict=True):
                    reviewed = await client.post(
                        f"/v1/proposals/{proposal.id}/reviews",
                        json={
                            "proposal_item_id": item.id,
                            "reviewer_actor_id": reviewer.id,
                            "decision": decision,
                            "rationale": f"HTTP {decision} decision",
                        },
                    )
                    proposal = ProposalResponse.model_validate(reviewed.json())
                return proposal

            partial = await prepare(["accept", "reject"], "Partially accepted")
            partial_first = await client.post(
                f"/v1/proposals/{partial.id}:apply",
                json={"applied_by_actor_id": reviewer.id},
            )
            partial_result = ProposalResponse.model_validate(partial_first.json())
            assert partial_result.status == "partially_accepted"
            partial_snapshot = (
                partial_result.applied_at,
                partial_result.applied_by_actor_id,
                tuple(tuple(item.created_canonical_ids) for item in partial_result.items),
                namespace.revision_token,
                session.query(Claim).count(),
                session.query(AuditEvent).count(),
            )
            partial_retry = await client.post(
                f"/v1/proposals/{partial.id}:apply",
                json={"applied_by_actor_id": retry_actor.id},
            )
            partial_retried = ProposalResponse.model_validate(partial_retry.json())
            assert (
                partial_retried.applied_at,
                partial_retried.applied_by_actor_id,
                tuple(tuple(item.created_canonical_ids) for item in partial_retried.items),
                namespace.revision_token,
                session.query(Claim).count(),
                session.query(AuditEvent).count(),
            ) == partial_snapshot

            rejected = await prepare(["reject"], "Rejected")
            rejected_first = await client.post(
                f"/v1/proposals/{rejected.id}:apply",
                json={"applied_by_actor_id": reviewer.id},
            )
            rejected_result = ProposalResponse.model_validate(rejected_first.json())
            assert rejected_result.status == "rejected"
            rejected_snapshot = (
                rejected_result.applied_at,
                rejected_result.applied_by_actor_id,
                namespace.revision_token,
                session.query(Claim).count(),
                session.query(AuditEvent).count(),
            )
            rejected_retry = await client.post(
                f"/v1/proposals/{rejected.id}:apply",
                json={"applied_by_actor_id": retry_actor.id},
            )
            rejected_retried = ProposalResponse.model_validate(rejected_retry.json())
            assert (
                rejected_retried.applied_at,
                rejected_retried.applied_by_actor_id,
                namespace.revision_token,
                session.query(Claim).count(),
                session.query(AuditEvent).count(),
            ) == rejected_snapshot

            stale = await prepare(["accept"], "Stale")
            namespace.revision_token += 1
            session.commit()
            stale_snapshot = (
                namespace.revision_token,
                session.query(Claim).count(),
                session.query(AuditEvent).count(),
            )
            for _ in range(2):
                stale_response = await client.post(
                    f"/v1/proposals/{stale.id}:apply",
                    json={"applied_by_actor_id": reviewer.id},
                )
                assert stale_response.status_code == 409
                stale_problem = ProblemDetail.model_validate(stale_response.json())
                assert stale_problem.code == "proposal.stale_base_revision"
                assert (
                    namespace.revision_token,
                    session.query(Claim).count(),
                    session.query(AuditEvent).count(),
                ) == stale_snapshot
    finally:
        app.dependency_overrides.clear()
