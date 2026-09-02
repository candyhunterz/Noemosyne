import Link from "next/link";
import { request as api } from "@/lib/generated-api/client";
import type { components } from "@/lib/generated-api/schema";

type ContextBundleResponse = components["schemas"]["ContextBundleResponse"];

export default async function ClaimDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const bundle = await api<ContextBundleResponse>(`/v1/claims/${id}/context`);
  return (
    <>
      <p className="pill">{bundle.assessment?.verdict ?? "unassessed"}</p>
      <h1>{bundle.claim?.wording}</h1>
      <p><Link href={`/claims/${id}/history`}>View belief history →</Link></p>
      <section className="card"><h2>Scope</h2><pre>{JSON.stringify(bundle.claim?.scope, null, 2)}</pre></section>
      <section className="card"><h2>Assessment</h2><p>{bundle.assessment?.rationale ?? "No accepted assessment."}</p><pre>{JSON.stringify(bundle.assessment?.profile, null, 2)}</pre></section>
      <h2>Evidence, grouped by dependency</h2>
      {bundle.evidence_groups.map((group, index) => <section className="card" key={group.dependency_group?.id ?? index}><h3>{group.dependency_group?.label ?? "Independent evidence"}</h3>{group.items.map((item) => <div key={item.evidence_link_id}><span className="pill">{item.stance}</span> <strong>{item.strength_band}</strong><p>{item.scope_match}</p>{item.argument ? <p>Argument: {item.argument.inference_scheme} · {item.argument.rationale}</p> : null}{item.sources.map((source) => <p key={source.fragment_id}><Link href={`/sources/${source.source_id}`}>{source.title}</Link> · <code>{JSON.stringify(source.locator)}</code></p>)}</div>)}</section>)}
      <h2>Open challenges</h2>{bundle.open_challenges.length ? bundle.open_challenges.map((challenge) => <div className="card" key={challenge.id}><strong>{challenge.category}</strong><p>{challenge.explanation}</p></div>) : <p className="meta">None recorded.</p>}
    </>
  );
}
