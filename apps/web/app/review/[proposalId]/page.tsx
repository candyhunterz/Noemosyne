import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { ApiProblemError, request as api } from "@/lib/generated-api/client";
import type { components } from "@/lib/generated-api/schema";

type ProposalResponse = components["schemas"]["ProposalResponse"];
type ActorListResponse = components["schemas"]["ActorListResponse"];

function errorMessage(error: unknown): string {
  return error instanceof ApiProblemError
    ? `${error.problem.code}: ${error.problem.detail}`
    : "The review operation failed unexpectedly";
}

async function recordDecision(formData: FormData): Promise<void> {
  "use server";
  const proposalId = String(formData.get("proposal_id"));
  let failure: string | null = null;
  try {
    await api<ProposalResponse>(`/v1/proposals/${proposalId}/reviews`, {
      method: "POST",
      body: JSON.stringify({
        proposal_item_id: String(formData.get("proposal_item_id")),
        reviewer_actor_id: String(formData.get("reviewer_actor_id")),
        decision: String(formData.get("decision")),
        rationale: String(formData.get("rationale")),
      }),
    });
  } catch (error: unknown) {
    failure = errorMessage(error);
  }
  revalidatePath(`/review/${proposalId}`);
  const query = failure ? `?error=${encodeURIComponent(failure)}` : "?saved=review";
  redirect(`/review/${proposalId}${query}`);
}

async function applyProposal(formData: FormData): Promise<void> {
  "use server";
  const proposalId = String(formData.get("proposal_id"));
  let failure: string | null = null;
  try {
    await api<ProposalResponse>(`/v1/proposals/${proposalId}:apply`, {
      method: "POST",
      body: JSON.stringify({
        applied_by_actor_id: String(formData.get("applied_by_actor_id")),
      }),
    });
  } catch (error: unknown) {
    failure = errorMessage(error);
  }
  revalidatePath(`/review/${proposalId}`);
  const query = failure ? `?error=${encodeURIComponent(failure)}` : "?saved=applied";
  redirect(`/review/${proposalId}${query}`);
}

export default async function ProposalReview({
  params,
  searchParams,
}: {
  params: Promise<{ proposalId: string }>;
  searchParams: Promise<{ error?: string; saved?: string }>;
}) {
  const { proposalId } = await params;
  const notice = await searchParams;
  const proposal = await api<ProposalResponse>(`/v1/proposals/${proposalId}`);
  const actorData = await api<ActorListResponse>(
    `/v1/namespaces/${proposal.namespace_id}/actors`,
  );
  const eligibleReviewers = actorData.actors.filter(
    (actor) => actor.id !== proposal.proposer_actor_id,
  );
  const canFinalize =
    proposal.status === "in_review" &&
    proposal.items.every((item) => item.effective_outcome !== null);

  return (
    <>
      <p className="pill">{proposal.status}</p>
      <h1>{proposal.title}</h1>
      <p>{proposal.description}</p>
      {notice.error ? <p className="card" role="alert">{notice.error}</p> : null}
      {notice.saved ? <p className="meta" role="status">Review state refreshed.</p> : null}

      <section className="card">
        <h2>Proposal provenance</h2>
        <dl>
          <dt>Proposal</dt><dd><code>{proposal.id}</code></dd>
          <dt>Namespace</dt><dd><code>{proposal.namespace_id}</code></dd>
          <dt>Proposer</dt><dd><code>{proposal.proposer_actor_id}</code></dd>
          <dt>Base revision</dt><dd>{proposal.base_revision_token}</dd>
          <dt>Recorded</dt><dd>{proposal.recorded_at}</dd>
          <dt>Submitted</dt><dd>{proposal.submitted_at ?? "not submitted"}</dd>
        </dl>
        <p className="meta">
          Trusted-local identity boundary: selecting an actor records provenance; it is not
          authentication. Run this UI only behind operator-controlled access.
        </p>
      </section>

      {proposal.items.map((item) => (
        <article className="card" key={item.id} data-testid={`proposal-item-${item.position}`}>
          <p className="pill">{item.status}</p>
          <h2>{item.position + 1}. {item.command_type}</h2>
          <h3>Candidate payload</h3>
          <pre>{JSON.stringify(item.payload, null, 2)}</pre>
          <h3>Preconditions</h3>
          <pre>{JSON.stringify(item.preconditions, null, 2)}</pre>
          <h3>Validation</h3>
          <pre>{JSON.stringify(item.validation_errors, null, 2)}</pre>
          <h3>Effective outcome</h3>
          <p>{item.effective_outcome ?? "No substantive decision"}</p>
          <h3>Append-only decisions</h3>
          {item.reviews.length ? item.reviews.map((review) => (
            <p key={review.id}>
              <strong>{review.decision}</strong> by <code>{review.reviewer_actor_id}</code>
              {" — "}{review.rationale} <span className="meta">({review.recorded_at})</span>
            </p>
          )) : <p className="meta">No decisions recorded.</p>}

          {proposal.status === "in_review" ? (
            <form action={recordDecision} data-testid={`review-form-${item.position}`}>
              <input type="hidden" name="proposal_id" value={proposal.id} />
              <input type="hidden" name="proposal_item_id" value={item.id} />
              <label>
                Trusted-local reviewer actor
                <select name="reviewer_actor_id" required>
                  {eligibleReviewers.map((actor) => (
                    <option value={actor.id} key={actor.id}>
                      {actor.display_name} ({actor.kind})
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Decision
                <select name="decision" required>
                  <option value="accept">Accept</option>
                  <option value="reject">Reject</option>
                  <option value="request_changes">Request changes</option>
                  <option value="abstain">Abstain</option>
                </select>
              </label>
              <label>
                Rationale
                <textarea name="rationale" required minLength={1} />
              </label>
              <button type="submit" disabled={eligibleReviewers.length === 0}>
                Record append-only decision
              </button>
            </form>
          ) : null}

          {item.created_canonical_ids.length ? (
            <p>Created canonical IDs: <code>{item.created_canonical_ids.join(", ")}</code></p>
          ) : null}
        </article>
      ))}

      <section className="card">
        <h2>Apply reviewed proposal</h2>
        <form action={applyProposal} data-testid="apply-proposal-form">
          <input type="hidden" name="proposal_id" value={proposal.id} />
          <label>
            Trusted-local applying actor
            <select name="applied_by_actor_id" required>
              {actorData.actors.map((actor) => (
                <option value={actor.id} key={actor.id}>
                  {actor.display_name} ({actor.kind})
                </option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={!canFinalize}>Apply or finalize reviewed items</button>
        </form>
        {!canFinalize && proposal.status === "in_review" ? (
          <p className="meta">Each item needs a substantive server-computed outcome first.</p>
        ) : null}
      </section>
    </>
  );
}
