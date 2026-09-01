import Link from "next/link";
import { api } from "@/lib/api";

export default async function ClaimDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const bundle = await api<any>(`/v1/claims/${id}/context`);
  return (
    <>
      <p className="pill">{bundle.assessment?.verdict ?? "unassessed"}</p>
      <h1>{bundle.claim?.wording}</h1>
      <p><Link href={`/claims/${id}/history`}>View belief history →</Link></p>
      <section className="card"><h2>Scope</h2><pre>{JSON.stringify(bundle.claim?.scope, null, 2)}</pre></section>
      <section className="card"><h2>Assessment</h2><p>{bundle.assessment?.rationale ?? "No accepted assessment."}</p><pre>{JSON.stringify(bundle.assessment?.profile, null, 2)}</pre></section>
      <h2>Evidence, grouped by dependency</h2>
      {bundle.evidence_groups.map((group: any, index: number) => <section className="card" key={group.dependency_group?.id ?? index}><h3>{group.dependency_group?.label ?? "Independent evidence"}</h3>{group.items.map((item: any) => <div key={item.evidence_link_id}><span className="pill">{item.stance}</span> <strong>{item.strength_band}</strong><p>{item.scope_match}</p>{item.sources.map((source: any) => <p key={source.fragment_id}><Link href={`/sources/${source.source_id}`}>{source.title}</Link> · <code>{JSON.stringify(source.locator)}</code></p>)}</div>)}</section>)}
      <h2>Open challenges</h2>{bundle.open_challenges.length ? bundle.open_challenges.map((challenge: any) => <div className="card" key={challenge.id}><strong>{challenge.category}</strong><p>{challenge.explanation}</p></div>) : <p className="meta">None recorded.</p>}
    </>
  );
}
