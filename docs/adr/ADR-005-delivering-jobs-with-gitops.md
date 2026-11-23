# ADR-005: How code and one-off Jobs are delivered with GitOps

- **Status:** Accepted
- **Date:** 2026-11-12
- **Phase:** 1

## Context

Argo CD makes the cluster match Git. Long-running services fit that model naturally, but some work is
an *action*, not a *state*: running database migrations, seeding reference data, ingesting filings.
New code also has to reach the cluster without anyone running `kubectl` by hand.

## Decisions

### 1. CI writes the new image tag back to Git

`git push` → GitHub Actions tests and builds the image → pushes it to GHCR as `sha-<commit>` →
commits that tag into the service's `kustomization.yaml` → Argo CD sees the change and deploys it.
Every deployment is therefore a Git commit (auditable, revertible). Images are only rebuilt when
their own inputs change (service folder, files copied into the image, its tests, or the workflow).

### 2. Pick the right Kubernetes object for each kind of work

| Work | Object | Why |
|---|---|---|
| Migrations (`db-migrate`) | Job as an Argo CD **Sync hook** | Must run once per release, before services use the schema |
| Reference data (`trades seed`) | Job as a **Sync hook**, wave -1 in its app | Runs on every release, before the generator and consumer update |
| Filing ingestion | **CronJob** | Recurring (daily); an ordinary resource, so a new image tag simply updates it |
| Generator, consumer | **Deployment** | Long-running |

### 3. A hook-only app needs a "tripwire" resource

Argo CD ignores hooks when deciding whether an app is out of sync. An app containing *only* a hook
(the first version of `db-migrate`) therefore always looked "Synced", auto-sync never ran, and the
migration never executed. Fix: the app also contains an ordinary ConfigMap (`db-migrate-release`)
holding the image tag. CI updates it together with the image, so every release creates a real
difference → sync → the hook runs. The `trades` app doesn't need one, because its Deployments change
with every new tag.

### 4. Things Argo CD must not fight over

The trade generator is switched on and off with `kubectl scale`. The `trades` app declares
`ignoreDifferences` on its `spec.replicas` with `RespectIgnoreDifferences=true`, so Argo CD neither
reports that as drift nor resets it (the same technique used with autoscalers).

## Consequences

- Argo CD polls Git every ~3 minutes (no webhook: the cluster accepts no inbound traffic), so a push
  takes ~5 minutes to land: CI build + poll. "Refresh" in the UI forces an immediate check.
- The first sync of a new app briefly fails because the `main` tag doesn't exist until CI pushes it;
  Argo CD's retry recovers once CI commits the real tag.
- Migrations must never be edited after they've run: Alembic tracks versions, not file contents.
