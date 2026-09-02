# ADR 0005: Canonical mutation is proposal-only

- Status: accepted
- Date: 2026-09-01

## Decision

Public clients submit allowlisted typed commands as immutable proposal items. A separate same-namespace reviewer records append-only decisions. Apply revalidates every canonical reference and actor against the proposal namespace, locks affected state, checks that namespace's revision token, recomputes the conservative outcome from all decisions, executes accepted items atomically, appends audit provenance, and advances the token.

PostgreSQL independently enforces the process side of this boundary with deferred constraint triggers on every canonical table. An accepted canonical row must resolve to an accepted item in a terminal accepted or partially accepted proposal, with a separated same-namespace effective acceptance and matching canonical/proposal namespace. Migration `0005_seal_terminal_provenance` makes that invariant durable after canonical insertion: terminal proposals and their items cannot be updated or deleted, and reviews can only be inserted while the parent proposal is `in_review`. There is no caller-controlled bypass.

Review insertion and apply both acquire a row lock on the parent proposal. This serializes the admission boundary: a concurrent review either commits before apply and participates in the shared conservative outcome, or observes the terminal proposal after apply and fails. Apply flushes item outcomes before moving the parent from `in_review` to its terminal status.

## Consequences

There are no direct canonical create/update/delete endpoints. `request_changes` takes precedence over rejection, rejection over acceptance, and abstention never authorizes apply. A failing accepted item rolls back the entire application transaction. Reapplying accepted, partially accepted, or rejected proposals returns the committed result without writes; a stale proposal consistently returns its original stale conflict. Operational corrections to terminal workflow provenance require a new proposal or restoration from a verified backup rather than SQL mutation.
