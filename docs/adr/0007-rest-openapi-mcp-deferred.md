# ADR 0007: REST/OpenAPI is canonical; MCP is deferred

- Status: accepted
- Date: 2026-09-01

## Decision

M1 publishes a versioned REST API and generated OpenAPI/TypeScript contract. An MCP adapter is deferred to M2 and will remain a thin consumer of the same application services.

## Consequences

There is one machine contract to test during M1 and no duplicated epistemic business logic in adapters or the web client.
