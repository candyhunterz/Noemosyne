import Link from "next/link";
import { request as api } from "@/lib/generated-api/client";
import type { components } from "@/lib/generated-api/schema";

type ProposalListResponse = components["schemas"]["ProposalListResponse"];

export default async function ReviewQueue() {
  const data = await api<ProposalListResponse>("/v1/proposals?status=in_review");
  return <><h1>Review queue</h1>{data.proposals.map((proposal) => <article className="card" key={proposal.id}><p className="pill">{proposal.status}</p><h2><Link href={`/review/${proposal.id}`}>{proposal.title}</Link></h2><p>{proposal.items.length} candidate mutations</p></article>)}</>;
}
