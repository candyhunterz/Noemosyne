import type { components } from "./generated-api/schema";

const API_URL = process.env.NOEMOSYNE_API_URL ?? "http://localhost:8000";

export type ApiProblem = components["schemas"]["ProblemDetail"];

export class ApiProblemError extends Error {
  constructor(public readonly problem: ApiProblem) {
    super(problem.detail);
    this.name = "ApiProblemError";
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!response.ok) {
    const fallback: ApiProblem = {
      type: "about:blank",
      title: "HTTP error",
      status: response.status,
      detail: response.statusText || "Noemosyne API request failed",
      code: "http.error",
    };
    const problem = (await response.json().catch(() => fallback)) as ApiProblem;
    throw new ApiProblemError(problem);
  }
  return response.json() as Promise<T>;
}
