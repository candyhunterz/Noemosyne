# Milestone 1 implementation notes

The repository implements the supplied `03` invariants and `14` acceptance brief. Referenced documents `00_EXECUTIVE_OVERVIEW.md`, `04_DATA_MODEL.md`, `07_MACHINE_INTERFACE.md`, `10_MVP_SPECIFICATION.md`, and the companion `examples/ai_research_seed.yaml` were not present in the source package, so no unstated field or error vocabulary from those files could be reproduced. The shipped schema uses every required M1 table and every constraint described in the available brief.

## Acceptance map

- Startup: pinned Docker images, Compose health checks, Alembic, `Makefile`.
- Domain invariants: framework-free enums/value objects and unit/property tests.
- Canonical store: all 31 tables, portable string checks, PostgreSQL-only production URL, append-only triggers.
- Provenance: accepted canonical rows point to proposal items; seed creates curator, reviewer, accepted proposal, review, revision, and audit records.
- Proposals: typed command allowlist; immutable submission; separation of duty; row locks; stale revision check; atomic apply; idempotent terminal result.
- History: recorded-time plus valid-time filtering in context bundles and cutoff tests.
- Retrieval: dependency-grouped, deterministically ordered context bundle with omissions; allowlisted graph traversal capped at depth 3 and 100 nodes.
- Interface: `/v1` REST routes, RFC 9457 problem responses, generated OpenAPI and TypeScript schema.
- Web: claim search/read/history, source view, review queue/detail, and activity routes.
- Seed: versioned Pydantic envelope, UUIDv5 mapping, content hash, transactional import, same-hash no-op.

## Deliberate boundaries

The review detail UI is read-only because M1 has no authentication model for safely choosing a reviewer identity in a browser. Review and apply remain fully available through the REST contract. PostgreSQL full-text ranking currently degrades to deterministic normalized substring matching; score fields are reserved for the planned indexed projection. MCP is deferred exactly as ADR 0007 requires.
