# Phase 1 — Data layer and real-time ingestion

**Goal:** get real SEC filings and a live synthetic trade stream into four data stores, searchable,
reproducible and measurable.

| "Done when" (from the project plan) | Status |
|---|---|
| 50+ filings are searchable | ✅ **60 filings**, 19,666 chunks, vector + keyword search verified |
| The stream runs for an hour with consumer lag under 5 s | ⏳ **Pending Step 1.5** (soak test). Short runs: avg lag 0.007 s, max 0.012 s |
| A Grafana panel shows throughput and lag | ⏳ **Pending Step 1.5** (metrics are already exposed and scraped) |

## What was built

```
EDGAR ──► ingest-edgar (CronJob, daily) ──► Items 1A/7/7A/8 ──► ~450-token chunks ──► bge-small embeddings
                                                                     │                       │
                                                                     ▼                       ▼
                                                              OpenSearch (BM25)      Postgres + pgvector
                                                                                     (filings · sections · chunks · embeddings)

GLEIF + fictional ──► trades seed (Sync hook) ──► desks · books · counterparties · customers ──► Postgres + Neo4j

trade-generator (~100/s) ──► Redis Stream "trades" ──► trade-consumer ──► Postgres: trades, exposures
                                                                     └──► Neo4j: (Desk)-[:TRADES_WITH]->(Counterparty)-[:SUBSIDIARY_OF]->(Bank)
```

| Step | Delivered |
|---|---|
| 1.0 Platform | 4th kind node (`workload: data`); `sentinel-data` StorageClass with fixed per-volume folders on the dev machine's disk, so data survives `make down`/`make up` (verified) |
| 1.1 Data stores | Postgres 17 + pgvector (CloudNativePG), OpenSearch 3.9, Redis 7.4, Neo4j, Prometheus + Grafana, all as Argo CD apps; passwords generated on the dev machine, never in Git |
| 1.2 Schema | Alembic migrations 0001–0003: 11 tables, HNSW vector index, PII registry; least-privilege roles `ingest_writer`, `stream_writer`, `trade_generator`, `readonly_analyst` ([data model](data-model.md)) |
| 1.3 EDGAR ingestion | 60 filings (3 × 10-K, 3 × 10-Q for each of 10 banks) → 177 sections → 19,666 chunks + embeddings, in Postgres and OpenSearch |
| 1.4 Trade stream | Reference data (8 desks, 24 books, 105 GLEIF subsidiaries + 150 fictional counterparties, 500 fake customers); generator; idempotent consumer |
| 1.6 Images & CI | GitHub Actions: lint, unit tests, migration test, trades integration test; images to GHCR; tag written back to Git for Argo CD |

## Numbers (2026-11-12)

| | |
|---|---|
| Filings / sections / chunks / embeddings | 60 / 177 / 19,666 / 19,666 |
| OpenSearch documents | 19,666 (matches Postgres) |
| Counterparties | 105 real (subsidiaries of the 10 allowlisted banks) + 150 fictional |
| Trades processed in the first run | 642,150 → 2,040 desk–counterparty exposure rows |
| Stream throughput / lag (1-minute sample) | 133 trades/s (incl. a burst), avg 0.007 s, max 0.012 s |
| Dev machine disk used | 16% of 145 GB |

## Problems hit, and what they taught

| Problem | Cause | Fix | Lesson |
|---|---|---|---|
| Migration Job never ran | An Argo CD app with only a hook always looks "Synced" | Release ConfigMap as a tripwire ([ADR-005](adr/ADR-005-delivering-jobs-with-gitops.md)) | Know what your controller compares |
| Ingestion "succeeded" but Postgres had 0 rows | psycopg default mode: `conn.transaction()` was a savepoint inside an uncommitted transaction | `autocommit=True`; OpenSearch reconcile deletes orphans | Verify writes from a *separate* connection |
| Only 1 10-K for big banks | SEC "recent" list holds ~1,000 filings; big banks file thousands of prospectuses | Read the paged history | Real APIs page; test against real data |
| `BK` not found | Bank of New York Mellon changed its ticker to `BNY` | Allowlist pins SEC CIKs and GLEIF LEIs | Use permanent IDs, not names |
| MD&A missing for Citi, WFC, BNY | Wrapped titles, "Financial Review", untitled MD&A | Layered fallbacks, each with a unit test | Tune parsers on the real corpus |
| Generator/consumer crash-looped | Kubernetes service links injected `REDIS_PORT=tcp://…` | `enableServiceLinks: false` | Docker tests can't see Kubernetes-only behaviour |
| `PS1: unbound variable`, shellcheck/ruff failures in CI | Strict flags over SSH; newer linter defaults | Adjusted flags; pinned rules in `ruff.toml` | Pin your tooling's rules |
| Overlap rarely applied | Overlap carries whole paragraphs only if ≤ 50 tokens | Recorded as a Phase 2 experiment ([ADR-006](adr/ADR-006-chunking-and-embeddings.md)) | Inspect the output, not just the tests |

## Decisions recorded

- [ADR-002](adr/ADR-002-phase-1-decisions.md): GHCR, public repo, entity allowlist, persistence, data node
- [ADR-003](adr/ADR-003-data-stores-in-cluster.md): data stores in the cluster vs AWS managed services
- [ADR-004](adr/ADR-004-redis-streams-vs-kafka.md): Redis Streams vs Kafka
- [ADR-005](adr/ADR-005-delivering-jobs-with-gitops.md): delivering code and Jobs with GitOps
- [ADR-006](adr/ADR-006-chunking-and-embeddings.md): chunking and embeddings, and the overlap finding

## Operating it (on the dev machine)

| Task | Command |
|---|---|
| Ingest new filings now / status | `make ingest` / `make ingest-status` |
| Trade stream on / off / status | `make stream-start` / `make stream-stop` / `make stream-status` |
| Database shell, migration status | `make psql` / `make db-status` |
| Tests (same as CI) | `make db-test` / `make trades-test` |

## Still open

- **Step 1.5:** Grafana dashboard, `make soak` (1 hour, lag < 5 s), `trades` retention. Then fill in the
  two ⏳ rows above with the soak result and a dashboard screenshot.
- Later extras: `make tunnels`, OpenSearch Dashboards.

## My notes (written by me)

> *Explain in your own words, as you would to an interviewer:*
>
> 1. *What "searchable" means here, and the difference between vector and keyword search (from the lab).*
> 2. *Why the consumer can receive the same trade twice, and why that doesn't double-count exposures.*
> 3. *One problem from the table above: what broke, how it was found, and how it was fixed.*
> 4. *What you'd measure in Phase 2 about chunk overlap, and why.*
