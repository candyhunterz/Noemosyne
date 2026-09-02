# Noemosyne

> Persistent epistemic memory for AI: claims, evidence, uncertainty, disagreement, and belief change—with provenance intact.

Noemosyne is an open-source, self-hostable system for representing not merely what sources say, but **what there is reason to believe, why, under which conditions, and how that view changed**.

It is **AI-first and human-accessible**. The primary product is a structured epistemic engine and machine interface. The web application is a window into the same state—not the system's center of gravity.

## The problem

Search and ordinary RAG retrieve documents or chunks. They do not reliably preserve proposition identity, scope, evidence dependence, disagreement, historical belief states, or the difference between an observation and an interpretation. A fluent synthesis can therefore hide where it came from and erase uncertainty.

Noemosyne makes those distinctions explicit:

- sources remain separate from the claims attributed to them;
- observations remain separate from interpretations;
- evidence only supports or challenges a claim in a recorded context;
- competing claims coexist;
- assessments are reasoned, versioned judgments, not magic confidence scores;
- agents propose changes, but cannot silently rewrite canonical knowledge;
- historical queries use only information available at the requested time;
- predictions have resolution rules and become calibration evidence.

## The smallest useful product

Milestone 1 is a **curated AI-research claim ledger**, not an autonomous world model. It supports:

1. registering source metadata and immutable source fragments;
2. creating context-qualified claims;
3. attaching supporting or challenging evidence with provenance;
4. representing typed relationships and evidence dependence;
5. accepting changes through a proposal and review workflow;
6. publishing immutable epistemic assessments and revision history;
7. retrieving compact, structured `EpistemicContextBundle` objects through the versioned REST API;
8. reviewing and applying proposals in the trusted-local web workflow.

MCP is future architecture deferred to Milestone 2 by ADR 0007. Autonomous evaluation, ingestion, model-provider calls, and search/RAG baseline experiments are not implemented in M1.

## Repository shape

```text
apps/
  api/          FastAPI HTTP service
  worker/       non-autonomous job runner stub
  web/          Next.js human interface
packages/
  domain/       pure epistemic rules and types
  db/           SQLAlchemy mappings, proposal application, and seed tooling
  retrieval/    historical context and bounded graph retrieval
  testkit/      shared test factories and assertions
examples/
  ai-research/  redistributable seed dataset
migrations/     Alembic schema and integrity enforcement
tests/          unit, property, contract, PostgreSQL integration, and Playwright E2E
docs/adr/       accepted architectural decisions
infra/docker/   pinned API and web runtime images
```

## Read the design

Start with:

- [`03_EPISTEMIC_MODEL.md`](03_EPISTEMIC_MODEL.md)
- [`14_CODEX_IMPLEMENTATION_BRIEF.md`](14_CODEX_IMPLEMENTATION_BRIEF.md)
- [`docs/IMPLEMENTATION_NOTES.md`](docs/IMPLEMENTATION_NOTES.md)
- [`docs/adr/`](docs/adr/)

The supplied numbered documents are normative in ascending specificity. The epistemic invariants in `03` and implementation acceptance criteria in `14` take precedence.

## Status

Milestone 1 is implemented as a PostgreSQL-backed FastAPI service, deterministic seed importer, typed proposal/review workflow, historical retrieval layer, and minimal Next.js read/review/apply interface.

## Quick start

Prerequisites are Docker Desktop, or Python 3.13 with `uv` plus Node.js with `pnpm`.

```sh
make start
```

The web UI starts at <http://localhost:3001> and development API docs at <http://localhost:8000/v1/docs>. Override the web port with `NOEMOSYNE_WEB_PORT` if needed. In another terminal, import the illustrative seed:

```sh
docker compose exec api noemosyne-seed import examples/ai-research/seed.yaml
```

For local development without containers:

```sh
make bootstrap
docker compose up -d db
make migrate
make seed
uv run uvicorn noemosyne_api.main:app --reload
pnpm dev
```

Run formatting, lint, strict typing, backend/contract/PostgreSQL tests, TypeScript checks, and the production web build with `make check`. With the stack and seed running, execute the browser acceptance workflow with `pnpm e2e`. Operational backup/restore and deployment boundaries are in [`docs/operations.md`](docs/operations.md).

## Architecture and security

PostgreSQL is the only canonical store. Accepted epistemic state enters through immutable proposals, independent item reviews, conservative append-only review outcomes, and atomic application. Claim context is filtered by both recorded and valid time; summaries retain the IDs needed to recover policy, evidence, source locators or arguments, and review provenance. The web app uses the generated OpenAPI boundary and server-computed review policy.

M1 has no authentication or tenant authorization, so it must run behind operator-controlled access and TLS outside local development. It performs no production model-provider calls and stores no copyrighted seed excerpts. See [`SECURITY.md`](SECURITY.md) before deployment.

## License

Software is Apache-2.0. Original documentation and curated example annotations are CC BY 4.0. Third-party metadata, text, and excerpts retain their own licenses; Noemosyne stores license and access metadata per source and does not redistribute content merely because it can retrieve it.
