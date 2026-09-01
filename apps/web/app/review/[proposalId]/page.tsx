import { api } from "@/lib/api";

export default async function ProposalReview({ params }: { params: Promise<{ proposalId: string }> }) {
  const { proposalId } = await params;
  const proposal = await api<any>(`/v1/proposals/${proposalId}`);
  return <><p className="pill">{proposal.status}</p><h1>{proposal.title}</h1><p>{proposal.description}</p>{proposal.items.map((item: any) => <article className="card" key={item.id}><h2>{item.position + 1}. {item.command_type}</h2><pre>{JSON.stringify(item.payload, null, 2)}</pre><h3>Validation</h3><pre>{JSON.stringify(item.validation_errors, null, 2)}</pre><h3>Decisions</h3>{item.reviews.map((review: any) => <p key={review.id}><strong>{review.decision}</strong> — {review.rationale}</p>)}</article>)}<p className="meta">Review decisions and apply actions are available through the typed REST workflow; authentication UI is intentionally deferred.</p></>;
}
