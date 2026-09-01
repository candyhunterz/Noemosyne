import { api } from "@/lib/api";

export default async function SourceDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const source = await api<any>(`/v1/sources/${id}`);
  return <><p className="pill">{source.kind}</p><h1>{source.title}</h1><p><a href={source.canonical_uri}>Canonical source ↗</a></p><section className="card"><h2>Access and license</h2><p>{source.license_basis}</p><pre>{JSON.stringify(source.access, null, 2)}</pre></section><h2>Fragments</h2>{source.fragments.map((fragment: any) => <div className="card" key={fragment.id}><pre>{JSON.stringify(fragment.locator, null, 2)}</pre><p className="meta">{fragment.license_basis}</p></div>)}</>;
}
