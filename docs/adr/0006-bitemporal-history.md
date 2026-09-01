# ADR 0006: Historical reads are bitemporal

- Status: accepted
- Date: 2026-09-01

## Decision

Historical reads independently filter `recorded_at` (what Noemosyne knew) and valid-time intervals (when a record applies in the represented domain). The knowledge cutoff defaults to now; domain time defaults to that cutoff.

## Consequences

Information discovered later cannot leak into earlier knowledge snapshots even when it describes an earlier event.
