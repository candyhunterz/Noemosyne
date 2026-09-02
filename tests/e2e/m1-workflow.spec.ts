import { expect, request, test } from "@playwright/test";
import type { components } from "../../apps/web/lib/generated-api/schema";

type ActivityResponse = components["schemas"]["ActivityResponse"];
type ActorListResponse = components["schemas"]["ActorListResponse"];
type ContextBundleResponse = components["schemas"]["ContextBundleResponse"];
type ClaimHistoryResponse = components["schemas"]["ClaimHistoryResponse"];
type NamespaceResponse = components["schemas"]["NamespaceResponse"];
type ProposalListResponse = components["schemas"]["ProposalListResponse"];
type ProposalResponse = components["schemas"]["ProposalResponse"];
type SearchResponse = components["schemas"]["SearchResponse"];

test("complete Milestone 1 proposal, history, provenance, and browser review workflow", async ({
  page,
}) => {
  const api = await request.newContext({
    baseURL: process.env.NOEMOSYNE_API_URL ?? "http://localhost:8000",
    extraHTTPHeaders: { "content-type": "application/json" },
  });
  const proposalListResponse = await api.get("/v1/proposals");
  expect(proposalListResponse.ok()).toBeTruthy();
  const initialProposals = (await proposalListResponse.json()) as ProposalListResponse;
  const seedProposal = initialProposals.proposals.find(
    (proposal) => proposal.items[0]?.command_type === "ImportSeedPackage",
  );
  expect(seedProposal).toBeDefined();
  const namespaceId = seedProposal!.namespace_id;
  const proposerId = seedProposal!.proposer_actor_id;
  const namespaceResponse = await api.get(`/v1/namespaces/${namespaceId}`);
  const namespace = (await namespaceResponse.json()) as NamespaceResponse;
  const actorsResponse = await api.get(`/v1/namespaces/${namespaceId}/actors`);
  const actors = (await actorsResponse.json()) as ActorListResponse;
  const reviewer = actors.actors.find((actor) => actor.id !== proposerId);
  expect(reviewer).toBeDefined();

  const searchResponse = await api.post("/v1/claims:search", {
    data: { namespace_id: namespaceId, query: "inference-time", limit: 20, verdicts: [] },
  });
  const search = (await searchResponse.json()) as SearchResponse;
  expect(search.results.length).toBeGreaterThan(0);
  const parentClaimId = search.results[0].claim_id;
  const parentContextResponse = await api.get(`/v1/claims/${parentClaimId}/context`);
  const parentContext = (await parentContextResponse.json()) as ContextBundleResponse;
  const parentHistoryResponse = await api.get(`/v1/claims/${parentClaimId}/history`);
  expect(parentHistoryResponse.ok()).toBeTruthy();
  const parentHistory = (await parentHistoryResponse.json()) as ClaimHistoryResponse;
  expect(parentHistory.claim_id).toBe(parentClaimId);
  expect(parentHistory.timeline.length).toBeGreaterThan(0);
  const sourceEvidence = parentContext.evidence_groups
    .flatMap((group) => group.items)
    .find((item) => item.sources.length > 0);
  expect(sourceEvidence).toBeDefined();
  const fragmentId = sourceEvidence!.sources[0].fragment_id;
  const policyId = sourceEvidence!.assessment_policy_id;
  const oldCutoff = new Date().toISOString();
  const claimId = crypto.randomUUID();
  const evidenceItemId = crypto.randomUUID();

  const createdResponse = await api.post("/v1/proposals", {
    data: {
      namespace_id: namespaceId,
      proposer_actor_id: proposerId,
      title: "E2E narrower inference-time claim",
      description: "Acceptance-level browser workflow fixture",
      base_revision_token: namespace.revision_token,
    },
  });
  let proposal = (await createdResponse.json()) as ProposalResponse;
  const items = [
    {
      command_type: "CreateClaim",
      payload: {
        id: claimId,
        wording: "On the seeded task scope, adaptive inference-time compute has documented comparative evidence.",
        scope_json: { parent_claim_id: parentClaimId, fixture: "playwright-e2e" },
        valid_from: "2025-01-01T00:00:00Z",
      },
      preconditions: {},
    },
    {
      command_type: "CreateEvidenceItem",
      payload: {
        id: evidenceItemId,
        kind: "source_fragment",
        source_fragment_ids: [fragmentId],
        description: "E2E evidence using an accepted seed fragment",
      },
      preconditions: {},
    },
    {
      command_type: "LinkEvidenceToClaim",
      payload: {
        claim_id: claimId,
        evidence_item_id: evidenceItemId,
        evaluator_actor_id: proposerId,
        assessment_policy_id: policyId,
        stance: "supports",
        directness: "direct",
        strength_band: "material",
        scope_match: "Matches the deliberately narrow E2E scope",
      },
      preconditions: {},
    },
  ] as const;
  for (const item of items) {
    const added = await api.post(`/v1/proposals/${proposal.id}/items`, { data: item });
    expect(added.ok()).toBeTruthy();
    proposal = (await added.json()) as ProposalResponse;
  }
  const validated = await api.post(`/v1/proposals/${proposal.id}:validate`);
  proposal = (await validated.json()) as ProposalResponse;
  expect(proposal.status).toBe("ready");
  const submitted = await api.post(`/v1/proposals/${proposal.id}:submit`);
  proposal = (await submitted.json()) as ProposalResponse;
  expect(proposal.status).toBe("in_review");

  await page.goto(`/review/${proposal.id}`);
  await expect(page.getByRole("heading", { name: proposal.title })).toBeVisible();
  await expect(page.getByText("Trusted-local identity boundary")).toBeVisible();
  for (let position = 0; position < items.length; position += 1) {
    const rationale = `E2E review rationale ${position}`;
    const form = page.getByTestId(`review-form-${position}`);
    await form.locator('select[name="reviewer_actor_id"]').selectOption(reviewer!.id);
    await form.locator('select[name="decision"]').selectOption("accept");
    await form.locator('textarea[name="rationale"]').fill(rationale);
    await form.getByRole("button", { name: "Record append-only decision" }).click();
    await expect(page.getByRole("status")).toContainText("Review state refreshed");
    await expect(page.getByText(rationale)).toBeVisible();
  }
  const applyForm = page.getByTestId("apply-proposal-form");
  await applyForm.locator('select[name="applied_by_actor_id"]').selectOption(reviewer!.id);
  await expect(applyForm.getByRole("button")).toBeEnabled();
  await applyForm.getByRole("button").click();
  await expect(page.locator(".pill").first()).toHaveText("accepted");
  await expect(page.getByText("Created canonical IDs:").first()).toBeVisible();

  const historicalResponse = await api.get(
    `/v1/claims/${claimId}/context?knowledge_cutoff=${encodeURIComponent(oldCutoff)}`,
  );
  expect(historicalResponse.status()).toBe(404);
  const currentResponse = await api.get(`/v1/claims/${claimId}/context`);
  expect(currentResponse.ok()).toBeTruthy();
  const current = (await currentResponse.json()) as ContextBundleResponse;
  expect(current.claim?.id).toBe(claimId);
  expect(current.evidence_groups.flatMap((group) => group.items)).toHaveLength(1);

  const finalProposalResponse = await api.get(`/v1/proposals/${proposal.id}`);
  const finalProposal = (await finalProposalResponse.json()) as ProposalResponse;
  expect(finalProposal.status).toBe("accepted");
  expect(finalProposal.items.every((item) => item.reviews.length === 1)).toBeTruthy();
  expect(finalProposal.items.every((item) => item.created_canonical_ids.length > 0)).toBeTruthy();
  const activityResponse = await api.get(`/v1/activity?namespace_id=${namespaceId}`);
  const activity = (await activityResponse.json()) as ActivityResponse;
  expect(
    activity.events.some(
      (event) => event.proposal_id === proposal.id && event.event_type === "proposal.applied",
    ),
  ).toBeTruthy();
  await api.dispose();
});
