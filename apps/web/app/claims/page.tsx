import Link from "next/link";
import { request as api } from "@/lib/generated-api/client";
import type { components } from "@/lib/generated-api/schema";

type SearchResponse = components["schemas"]["SearchResponse"];
type SearchResult = components["schemas"]["SearchResultResponse"];

export default async function Claims({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const params = await searchParams;
  const query = params.q ?? "";
  const namespace = params.namespace ?? "";
  let results: SearchResult[] = [];
  if (query && namespace) {
    const data = await api<SearchResponse>("/v1/claims:search", {
      method: "POST",
      body: JSON.stringify({ namespace_id: namespace, query, limit: 50, verdicts: [] }),
    });
    results = data.results;
  }
  return (
    <>
      <h1>Claim ledger</h1>
      <form><input name="namespace" defaultValue={namespace} placeholder="Namespace UUID" /> <input name="q" defaultValue={query} placeholder="Search claims" /> <button>Search</button></form>
      <table><thead><tr><th>Claim</th><th>Scope</th></tr></thead><tbody>
        {results.map((result) => <tr key={result.claim_id}><td><Link href={`/claims/${result.claim_id}`}>{result.wording}</Link></td><td><code>{JSON.stringify(result.scope)}</code></td></tr>)}
      </tbody></table>
      {!query && <p className="meta">Enter the namespace ID shown by the seed import, plus a search phrase.</p>}
    </>
  );
}
