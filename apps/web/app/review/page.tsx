import Link from "next/link";
import { api } from "@/lib/api";

export default async function ReviewQueue() {
  const data = await api<any>("/v1/proposals?status=in_review");
  return <><h1>Review queue</h1>{data.proposals.map((proposal: any) => <article className="card" key={proposal.id}><p className="pill">{proposal.status}</p><h2><Link href={`/review/${proposal.id}`}>{proposal.title}</Link></h2><p>{proposal.items.length} candidate mutations</p></article>)}</>;
}
