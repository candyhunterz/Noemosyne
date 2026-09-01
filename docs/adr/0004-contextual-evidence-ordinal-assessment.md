# ADR 0004: Evidence is contextual and assessments are ordinal profiles

- Status: accepted
- Date: 2026-09-01

## Decision

Evidence force belongs to an attributed link between an evidence item and claim, with stance, directness, strength band, scope fit, caveats, policy, and dependency. Assessments use reasoned ordinal dimensions, never a generic probability of truth.

## Consequences

No `is_fact`, trust score, or weighted confidence field exists. Dependency grouping prevents naive evidence counting.
