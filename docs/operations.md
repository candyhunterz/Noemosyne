# Operations

## Local start

Run `make start`, migrate/import automatically through the API container startup, then run `docker compose exec api noemosyne-seed import examples/ai-research/seed.yaml` if the example directory is mounted or import from a local `uv` environment. The API is at `http://localhost:8000/v1/docs`; the web UI is at `http://localhost:3000`.

## Backup and restore

Canonical history is append-only, so PostgreSQL backups are the recovery unit. Create a consistent custom-format backup with `pg_dump --format=custom --dbname "$DATABASE_URL" --file noemosyne.dump`. Restore only into a fresh database using `pg_restore --clean --if-exists --exit-on-error`. Verify the Alembic revision, namespace revision tokens, audit counts, and seed package hashes before directing clients to it.

Automated migration downgrade is intentionally disabled because dropping epistemic history is destructive. Roll back an application release while retaining the forward-compatible database, or restore a verified pre-migration backup into a fresh database.

## Security posture

The M1 service has no model-provider calls and logs identifiers/hashes rather than source text. It is intended for a trusted local or private network until authentication, authorization, rate limits, TLS termination, and tenant isolation are deployed by the operator. Never expose the development Compose credentials publicly.
