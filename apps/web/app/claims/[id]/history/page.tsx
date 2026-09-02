import { request as api } from "@/lib/generated-api/client";
import type { components } from "@/lib/generated-api/schema";

type ClaimHistoryResponse = components["schemas"]["ClaimHistoryResponse"];

export default async function ClaimHistory({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const history = await api<ClaimHistoryResponse>(`/v1/claims/${id}/history`);
  return <><h1>Belief history</h1>{history.timeline.map((entry) => <article className="card" key={entry.id}><p className="pill">{entry.verdict}</p><p>{entry.rationale}</p><p className="meta">Recorded {entry.recorded_at}</p></article>)}<h2>Two-point diff</h2><pre>{JSON.stringify(history.comparison, null, 2)}</pre></>;
}
