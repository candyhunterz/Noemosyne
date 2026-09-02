# ADR 0002: Append-only domain history, not universal event sourcing

- Status: accepted
- Date: 2026-09-01

## Decision

Accepted epistemic rows are immutable and corrected through new rows with `supersedes_id` plus explicit revision events. Current-state tables remain directly queryable; the system does not reconstruct all state from a universal event stream.

PostgreSQL triggers reject accepted-row `UPDATE` and `DELETE` without consulting caller-controlled session settings. The one mutable projection in M1, `claims.current_version_id`, advances only through the `SECURITY DEFINER` function `noemosyne_advance_claim_version`. Its owner is a dedicated `NOLOGIN` role. The function validates the same-namespace in-review proposal item, the conservative append-only review outcome, and the exact old-to-new supersession link before performing that single-column update.

## Consequences

Historical rationale is inspectable without imposing event-sourcing complexity. Application clients cannot enable mutation with a custom GUC; the former `noemosyne.accepting_proposal` setting has no effect. Claim versions and assessments retain queryable supersession chains, while recorded-time and valid-time queries continue to select immutable rows.
