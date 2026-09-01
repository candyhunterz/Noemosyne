# ADR 0005: Canonical mutation is proposal-only

- Status: accepted
- Date: 2026-09-01

## Decision

Public clients submit allowlisted typed commands as immutable proposal items. A separate reviewer records append-only decisions. Apply revalidates, locks affected state, checks the namespace revision token, executes accepted items atomically, appends audit provenance, and advances the token.

## Consequences

There are no direct canonical create/update/delete endpoints. A failing accepted item rolls back the entire application transaction.
