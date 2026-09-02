# ADR 0005: Canonical mutation is proposal-only

- Status: accepted
- Date: 2026-09-01

## Decision

Public clients submit allowlisted typed commands as immutable proposal items. A separate same-namespace reviewer records append-only decisions. Apply revalidates every canonical reference and actor against the proposal namespace, locks affected state, checks that namespace's revision token, recomputes the conservative outcome from all decisions, executes accepted items atomically, appends audit provenance, and advances the token.

## Consequences

There are no direct canonical create/update/delete endpoints. `request_changes` takes precedence over rejection, rejection over acceptance, and abstention never authorizes apply. A failing accepted item rolls back the entire application transaction.
