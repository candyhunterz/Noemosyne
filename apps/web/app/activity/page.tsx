import { api } from "@/lib/api";

export default async function Activity() {
  const data = await api<any>("/v1/activity");
  return <><h1>Accepted activity</h1>{data.events.map((event: any) => <article className="card" key={event.id}><p className="pill">{event.event_type}</p><p>{event.object_type} · <code>{event.object_id}</code></p><p className="meta">{event.recorded_at}</p></article>)}</>;
}
