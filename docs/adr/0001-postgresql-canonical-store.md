# ADR 0001: PostgreSQL is the sole canonical store

- Status: accepted
- Date: 2026-09-01

## Decision

PostgreSQL 18 stores every canonical M1 object, proposal, review, job, and audit event. Other indexes or caches may be rebuilt projections and cannot accept canonical mutations.

## Consequences

Transactions, constraints, row locks, bitemporal queries, and backups share one consistency boundary. M1 does not add a graph database, queue, or vector search service.
