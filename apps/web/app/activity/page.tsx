import { request as api } from "@/lib/generated-api/client";
import type { components } from "@/lib/generated-api/schema";

type ActivityResponse = components["schemas"]["ActivityResponse"];

export default async function Activity() {
  const data = await api<ActivityResponse>("/v1/activity");
  return <><h1>Accepted activity</h1>{data.events.map((event) => <article className="card" key={event.id}><p className="pill">{event.event_type}</p><p>{event.object_type} · <code>{event.object_id}</code></p><p className="meta">{event.recorded_at}</p></article>)}</>;
}
