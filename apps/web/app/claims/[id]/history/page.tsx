import { api } from "@/lib/api";

export default async function ClaimHistory({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const history = await api<any>(`/v1/claims/${id}/history`);
  return <><h1>Belief history</h1>{history.timeline.map((entry: any) => <article className="card" key={entry.id}><p className="pill">{entry.verdict}</p><p>{entry.rationale}</p><p className="meta">Recorded {entry.recorded_at}</p></article>)}<h2>Two-point diff</h2><pre>{JSON.stringify(history.comparison, null, 2)}</pre></>;
}
