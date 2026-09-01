# ADR 0002: Append-only domain history, not universal event sourcing

- Status: accepted
- Date: 2026-09-01

## Decision

Accepted epistemic rows are immutable and corrected through superseding rows and explicit revision events. Current-state tables remain directly queryable; the system does not reconstruct all state from a universal event stream.

## Consequences

Historical rationale is inspectable without imposing event-sourcing complexity. PostgreSQL triggers reject direct accepted-row mutation outside the controlled proposal application transaction.
