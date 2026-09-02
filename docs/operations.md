# Operations

## Local start

Run `make start`, migrate/import automatically through the API container startup, then run `docker compose exec api noemosyne-seed import examples/ai-research/seed.yaml` if the example directory is mounted or import from a local `uv` environment. The API is at `http://localhost:8000/v1/docs`; the web UI is at `http://localhost:3001`. Set `NOEMOSYNE_WEB_PORT` to override the web port. Run the browser acceptance workflow with `pnpm e2e` after installing Chromium with `pnpm exec playwright install chromium`.

## Ledger mutation boundary

Accepted ledger rows reject direct updates and deletes in PostgreSQL. Setting `noemosyne.accepting_proposal`, any other custom GUC, or transaction-local configuration does not bypass the triggers. Claim wording revisions insert a new `claim_versions` row with `supersedes_id`; the narrowly scoped `noemosyne_advance_claim_version` security-definer function validates proposal namespace, review outcome, and the supersession edge before advancing the current-version projection. Its owner, `noemosyne_projection_owner`, is `NOLOGIN` and must never be granted to application or operator login roles.

Operational SQL must not invoke the projection function as a repair shortcut. Corrections use the normal proposal/review/apply workflow. Restore verification includes checking that accepted rows reject `UPDATE`/`DELETE`, the projection role remains `NOLOGIN`, and supersession chains have no missing targets or cycles.

Migration `0004_process_provenance` adds deferred constraint triggers to every canonical table. At commit, each accepted row must resolve to an accepted proposal item under an accepted or partially accepted proposal, with an effective same-namespace independent acceptance and no rejecting or request-changes decision. The row's explicit or derived namespace must match the proposal namespace. These checks have no session switch or operational bypass; failed repair imports must be corrected as proposals or restored from a verified backup.

Migration `0005_seal_terminal_provenance` seals that provenance after application. Accepted, partially accepted, rejected, and stale proposals reject every update and delete; items under those proposals do the same. Review decisions are admitted only while the parent proposal is `in_review`. Review insertion, item mutation, and apply serialize through a PostgreSQL row lock on the parent proposal, so a racing review either commits before apply and affects the conservative outcome or fails after the terminal transition. Seed import follows the same order: in-review proposal, valid item, independent acceptance, accepted item, terminal proposal, then canonical rows. The migration revalidates all existing accepted canonical rows before installation and fails rather than sealing an already-invalid database.

## Backup and restore

Canonical history is append-only, so PostgreSQL backups are the recovery unit. Create a consistent custom-format backup with `pg_dump --format=custom --dbname "$DATABASE_URL" --file noemosyne.dump`. Restore only into a fresh database using `pg_restore --clean --if-exists --exit-on-error`. Verify the Alembic revision, namespace revision tokens, audit counts, and seed package hashes before directing clients to it.

Automated migration downgrade is intentionally disabled because dropping epistemic history is destructive. Roll back an application release while retaining the forward-compatible database, or restore a verified pre-migration backup into a fresh database.

## Security posture

The M1 service has no model-provider calls and logs identifiers/hashes rather than source text. Reviewer and applying actors are explicitly selected trusted-local provenance identities; that selection is not authentication. The service is intended for a trusted local or private network until authentication, authorization, rate limits, TLS termination, and tenant isolation are deployed by the operator. Never expose the development Compose credentials publicly.
