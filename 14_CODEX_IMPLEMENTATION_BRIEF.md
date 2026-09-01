# Codex implementation brief — Milestone 1

## Directive

Build Noemosyne Milestone 1 exactly as specified here and in the supporting documents. Do not expand scope to autonomous agents, full document ingestion, a graph database, forecasting, or a polished knowledge atlas.

Milestone 1 is complete when a reviewer can import the deterministic illustrative seed, inspect claims/evidence/assessments, submit and review typed proposals, accept them transactionally, reconstruct historical claim state without temporal leakage, and retrieve a structured context bundle through a tested REST API.

## Product invariant

No accepted epistemic object may exist without inspectable content/process provenance, and no agent or API client may silently rewrite accepted history.

## Authoritative decisions

- Claims are stable identities for scope-qualified propositions.
- Assertions attribute a stance to an actor/source; they are not Noemosyne's assessment.
- Evidence is a contextual, attributed link from an evidence item to a claim.
- “Fact” is not a table or object type.
- Assessments use structured ordinal profiles, not generic numeric truth confidence.
- Accepted records are superseded, not overwritten or hard-deleted.
- Historical reads filter by `recorded_at` as well as valid time.
- All canonical changes originate in a proposal and accepted item-level review.
- PostgreSQL is the only canonical store.
- Milestone 1 has no production model-provider calls.

## Stack

- Python 3.13
- FastAPI, Pydantic v2
- SQLAlchemy 2.0, Alembic, psycopg 3
- PostgreSQL 18 with pgvector extension installed (M1 may leave embeddings unused)
- `uv` workspace and lockfile
- pytest, pytest-asyncio, Hypothesis, Testcontainers
- Ruff and mypy strict for domain/application packages
- Next.js 16.3 Active LTS, React, TypeScript, pnpm, only for the minimal review/read UI
- Docker Compose
- OpenTelemetry SDK with console/no-op local exporter configuration

At implementation time, pin current patched versions in lockfiles. Do not hard-code floating `latest` image tags.

## Repository structure

```text
noemosyne/
  apps/
    api/noemosyne_api/
      main.py
      dependencies.py
      routes/
      schemas/
    worker/noemosyne_worker/
      main.py
    web/
      app/
      components/
      lib/generated-api/
  packages/
    domain/noemosyne_domain/
      actors.py
      sources.py
      claims.py
      evidence.py
      assessments.py
      proposals.py
      events.py
      errors.py
    db/noemosyne_db/
      models/
      repositories/
      session.py
    retrieval/noemosyne_retrieval/
      context_bundle.py
      graph_trace.py
    testkit/noemosyne_testkit/
      factories.py
      assertions.py
  migrations/versions/
  examples/ai-research/
    seed.yaml
    README.md
  tests/
    unit/
    integration/
    contract/
    property/
    e2e/
  docs/adr/
  infra/docker/
  scripts/
  compose.yaml
  pyproject.toml
  uv.lock
  pnpm-workspace.yaml
  package.json
  LICENSE
  CONTRIBUTING.md
  GOVERNANCE.md
  CODE_OF_CONDUCT.md
  SECURITY.md
  README.md
```

One root command should run backend checks; one should start the stack. Prefer a small `justfile` or documented `make` targets, but do not require a globally installed task runner beyond Docker, uv, and pnpm.

## Milestone 1 schema

Implement this subset now. Preserve names unless PostgreSQL requires a documented adjustment.

### Required tables

1. `namespaces`
2. `actors`
3. `entities`
4. `entity_aliases`
5. `claims`
6. `claim_versions`
7. `claim_entities`
8. `assertions`
9. `source_artifacts`
10. `source_fragments`
11. `evidence_items`
12. `evidence_item_sources`
13. `evidence_dependency_groups`
14. `evidence_dependency_members`
15. `evidence_links`
16. `arguments`
17. `argument_premises`
18. `challenges`
19. `claim_relations`
20. `assessment_policies`
21. `epistemic_assessments`
22. `assessment_inputs`
23. `revision_events`
24. `revision_impacts`
25. `questions`
26. `question_claims`
27. `proposals`
28. `proposal_items`
29. `review_decisions`
30. `audit_events`
31. `jobs`

Defer observations/experiments, forecasts, agent runs, embeddings/search projections, and plugin tables. Seed evidence may point directly to source fragments in M1.

### Required columns and constraints

Use the full definitions in `04_DATA_MODEL.md`, with these M1 clarifications:

- `claims.current_version_id` is nullable only during the transaction creating the first version; expose no incomplete claim.
- `claim_versions.scope_json` is non-null and defaults to `{}` only for explicitly scope-independent logical claims.
- `source_fragments` may have null `stored_text` but require `locator_json`, `text_hash` when text exists, and `license_basis`.
- `evidence_items.kind` in M1 is `source_fragment` or `argument`.
- `evidence_links` require `stance`, `directness`, `strength_band`, `scope_match`, evaluator, and assessment policy.
- accepted `incompatible_with` requires non-empty `context_json`.
- an assessment requires at least one `assessment_input` unless verdict is `unassessed`.
- `revision_events.before_assessment_id` is null only for the initial assessment.
- proposals are immutable after submission; proposal items are immutable after proposal submission.
- review decisions are append-only; policy decides effective outcome.
- acceptance writes canonical rows and an audit event in one transaction.
- accepted ledger rows reject direct `UPDATE`/`DELETE`; lifecycle uses new/superseding rows.

### Status vocabularies

Use string-backed domain enums plus database checks:

```text
record: proposed | accepted | superseded | withdrawn | rejected
proposal: draft | validating | ready | in_review | accepted | partially_accepted | rejected | stale
proposal item: pending | valid | invalid | accepted | rejected | stale
review: accept | reject | request_changes | abstain
evidence stance: supports | challenges | contextualizes
verdict: unassessed | insufficient_evidence | contested |
         provisionally_supported | well_supported |
         provisionally_challenged | well_refuted
```

Do not expose database enum types; migration of vocabulary should not require rewriting PostgreSQL enum internals.

## Domain commands

Implement typed application commands independent of HTTP:

- `RegisterSourceArtifact`
- `AddSourceFragment`
- `CreateClaim`
- `AddClaimVersion`
- `AddAssertion`
- `CreateEvidenceItem`
- `LinkEvidenceToClaim`
- `CreateEvidenceDependencyGroup`
- `AddEvidenceDependencyMember`
- `RelateClaims`
- `CreateArgument`
- `RaiseChallenge`
- `CreateAssessment`
- `CreateRevisionEvent`
- `CreateQuestion`
- `CreateProposal`
- `AddProposalItem`
- `SubmitProposal`
- `RecordReviewDecision`
- `ApplyAcceptedProposal`

Candidate proposal payloads parse into these commands. Never execute arbitrary table/field operations from JSON.

## Proposal acceptance algorithm

In one database transaction:

1. lock proposal and affected identity/current-version rows;
2. verify proposal is submitted/in-review and not previously applied;
3. compare `base_revision_token` and per-item preconditions;
4. recompute required review outcome and separation-of-duty rules;
5. parse accepted item payloads into typed commands;
6. run all domain invariants again;
7. execute accepted commands in item order;
8. write supersession/revision links;
9. append audit events and advance namespace revision token;
10. mark accepted/rejected/stale item outcomes and proposal aggregate status;
11. commit and return created canonical IDs.

Any failing accepted item rolls back the transaction. Partial acceptance refers to review selection before apply, not partial database commit.

## API

Prefix all routes with `/v1`. Publish OpenAPI at `/v1/openapi.json` and docs only in development by default.

### Required reads

```text
GET  /v1/health/live
GET  /v1/health/ready
GET  /v1/namespaces/{namespace_id}
GET  /v1/claims/{claim_id}
GET  /v1/claims/{claim_id}/context
GET  /v1/claims/{claim_id}/history
POST /v1/claims:search
POST /v1/graph:trace
GET  /v1/sources/{source_id}
GET  /v1/activity
```

### Required proposal operations

```text
POST /v1/proposals
POST /v1/proposals/{proposal_id}/items
POST /v1/proposals/{proposal_id}:validate
POST /v1/proposals/{proposal_id}:submit
GET  /v1/proposals/{proposal_id}
POST /v1/proposals/{proposal_id}/reviews
POST /v1/proposals/{proposal_id}:apply
```

### Query semantics

`GET /claims/{id}/context` accepts:

- `knowledge_cutoff` default now;
- `domain_time` default equal to cutoff;
- `max_evidence_per_stance` default 20, max 100;
- `include_history_summary` default true;
- `include_open_challenges` default true.

It returns the bundle shape in `07_MACHINE_INTERFACE.md`, deterministic ordering, dependency grouping, and omissions.

`GET /claims/{id}/history` accepts either one cutoff or `from_cutoff`/`to_cutoff` and returns assessment/revision diffs.

`POST /claims:search` in M1 uses PostgreSQL full-text plus normalized substring fallback. The response schema reserves component scores for later vector retrieval.

`POST /graph:trace` supports only allowlisted claim relations, max depth 3, max nodes 100.

Use RFC 9457 problem details and stable error codes listed in `07_MACHINE_INTERFACE.md`.

## Minimal web UI

Build functionality, not final visual polish:

- `/claims`: search/filter table;
- `/claims/[id]`: claim/scope, current assessment, dependency-grouped evidence, challenges, history link;
- `/claims/[id]/history`: revision timeline and two-point diff;
- `/sources/[id]`: metadata, license/access, fragments/locators;
- `/review`: proposal queue;
- `/review/[proposalId]`: source/candidate/validation, item decisions, apply action;
- `/activity`: accepted audit/epistemic events.

Generate the TypeScript client from OpenAPI. The web app contains no duplicated verdict or relation business rules.

## Seed import/export

Use the companion `examples/ai_research_seed.yaml` as the design source, expand it into the repository's `examples/ai-research/seed.yaml`, and validate it with a versioned Pydantic import model.

Import requirements:

- deterministic IDs or stable symbolic-ID mapping;
- transactionally all-or-nothing;
- idempotent by seed package ID/version/hash;
- source locators and annotations only; no copyrighted PDFs;
- imported accepted records include a synthetic human-curator actor and import proposal/review/audit provenance;
- a second import is a no-op with the same result report;
- export/import round trip preserves canonical semantics and history.

## Coding conventions

- Domain layer has no framework or database imports.
- Application services depend on repository protocols; database package implements them.
- Pydantic API/import models are separate from domain dataclasses/value objects and SQLAlchemy models.
- Use `Decimal` for forecast/statistical numeric values when added later; do not use float for future probability APIs.
- All times are timezone-aware UTC.
- Functions and modules use precise epistemic names; do not shorten `assessment` to `score` or `source_fragment` to `citation`.
- No boolean `is_fact`, `is_true`, or `trusted` fields.
- No generic `metadata` dumping when the field participates in invariants or queries.
- Public functions/types are documented; significant decisions receive ADRs.
- Logging uses structured IDs and hashes, not full source text.
- No secrets, provider keys, or live external calls in tests.

## Test strategy

### Unit tests

- value objects and enum validation;
- claim scope and version rules;
- evidence-link requirements;
- contradiction context rule;
- assessment profile and input rule;
- review separation and outcome calculation;
- historical interval selection;
- deterministic context-bundle ordering.

### Property tests

- accepted records cannot lose provenance;
- supersession chains are acyclic;
- historical cutoff never returns records added after cutoff;
- import(export(state)) is semantically equivalent;
- proposal apply is idempotent;
- any failed accepted item leaves no canonical side effects;
- bounded graph trace never exceeds limits or returns disallowed relations.

### Integration tests with real PostgreSQL

- migrations from empty database;
- all check/unique/foreign-key/partial-index constraints;
- concurrent duplicate claim/source proposals;
- stale base revision conflict;
- transaction rollback;
- append-only triggers/permissions;
- audit event transactionality;
- seed import twice;
- historical queries with recorded/valid time differences.

### Contract tests

- OpenAPI snapshot reviewed for intentional changes;
- all examples validate against response schemas;
- generated TypeScript client compiles;
- RFC 9457 error codes and statuses;
- no internal-only fields or source text leakage.

### End-to-end tests

1. import seed;
2. find a claim;
3. inspect context/history;
4. create proposal adding a narrower claim and evidence;
5. validate/submit/review/apply;
6. verify old cutoff unchanged and current context revised;
7. verify activity and audit provenance.

## Milestone 1 acceptance criteria

- Fresh clone + documented prerequisites starts with one command sequence.
- All migrations apply to PostgreSQL 18 and pass downgrade-policy documentation (no destructive automated downgrade required).
- Seed import is deterministic, idempotent, and passes round-trip semantic comparison.
- Every accepted evidence link resolves to a source fragment and complete source metadata/license basis.
- Source assertions are not returned as accepted assessment unless separately assessed.
- Direct canonical mutation endpoints do not exist.
- Proposal review and application enforce separation of duty and stale-base checks.
- Accepted history is append-only and supersession/revision chains are queryable.
- Historical fixtures show zero temporal leakage.
- Context bundle separates support/challenge/context, groups evidence dependency, includes policy/provenance, and reports omissions.
- Graph trace is typed and bounded.
- OpenAPI is generated and TypeScript client compiles.
- Minimal web workflows work without client-side business-rule duplication.
- All unit/property/integration/contract/E2E tests pass in CI.
- Ruff, mypy, TypeScript, and build checks pass.
- No critical/high dependency or container vulnerabilities at release, with documented exception process for false positives.
- README documents architecture, local run, tests, seed, backup/restore, and security posture.
- Apache-2.0 software licensing, CC BY 4.0 annotation licensing, DCO contribution rules, governance, code of conduct, and security reporting documents are present.

## Required ADRs

1. PostgreSQL as sole canonical store.
2. Append-only domain history instead of universal event sourcing.
3. Claim versus assertion identity.
4. Contextual evidence links and ordinal assessments.
5. Proposal-only canonical mutation.
6. Bitemporal historical semantics.
7. REST/OpenAPI canonical contract; MCP deferred to M2.

## Recommended implementation sequence

1. Scaffold workspace, CI, formatting/type checks, Compose, health endpoint.
2. Implement domain value objects, commands, and invariant tests.
3. Implement PostgreSQL mappings and initial migration.
4. Implement repositories, transaction boundary, audit append, namespace revision token.
5. Implement seed import and database integrity/property tests.
6. Implement proposal lifecycle and transactional application.
7. Implement claim/source/history read services.
8. Implement deterministic context bundle and bounded graph trace.
9. Expose REST/OpenAPI and generate TypeScript client.
10. Build minimal web read/review routes.
11. Add E2E workflow, backup/restore docs, security and release checks.
12. Run the full acceptance checklist and publish the M1 fixture report.

Do not start the model-agent pipeline until M1 is accepted.

## Non-goals reminder

Do not add Neo4j, Redis, Kafka, Celery, GraphQL, autonomous crawling, LangChain-style agent frameworks, generic causal edges, forecast dashboards, user reputation, automatic source trust scores, or one-number claim confidence. These are not “helpful extras”; they would weaken the milestone's testability.

## Handoff output expected from Codex

- working repository;
- complete migrations and seed;
- generated OpenAPI and client;
- passing test/quality/security reports;
- ADRs;
- implementation notes mapping every acceptance criterion to code/tests;
- list of deliberate deviations, each justified before implementation if it changes an invariant or scope.
