# services/db — schema migrations

Alembic migrations for the Sentinel Desk Postgres database, written as plain SQL.

| Migration | What it does |
|---|---|
| `0001_initial_schema` | Tables, indexes (including the pgvector HNSW index), PII registry and column comments |
| `0002_role_grants` | What each service role may read or write; the analyst role gets no PII columns |

The data model diagram is in [`docs/data-model.md`](../../docs/data-model.md).

## How it runs

1. GitHub Actions builds this folder into `ghcr.io/techarx/sentinel-db-migrate`, then commits the new image tag to `deploy/apps/db-migrate/kustomization.yaml`.
2. Argo CD sees the new tag and runs the `db-migrate` Job (`alembic upgrade head`).
3. Alembic records applied migrations in the `alembic_version` table, so each one runs once.

## Adding a migration

1. Copy the latest file in `migrations/versions/`, bump the number, set `down_revision` to the previous one.
2. Write `upgrade()` and `downgrade()` SQL.
3. Run `make db-test` (on the dev machine) to apply it up, down and up again against a throwaway Postgres.
4. Commit and push; CI tests it again, builds the image and rolls it out.

Never edit a migration that has already run in the cluster; add a new one.

## Connection settings

Standard libpq variables: `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSSLMODE` (default `require`).
