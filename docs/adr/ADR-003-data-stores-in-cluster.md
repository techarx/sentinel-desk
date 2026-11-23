# ADR-003: Run the data stores inside the cluster (for now)

- **Status:** Accepted
- **Date:** 2026-11-12
- **Phase:** 1 (revisit in Phase 8)

## Context

Sentinel Desk needs four data stores: Postgres with pgvector (source of truth, vector search),
OpenSearch (keyword search), Redis (trade stream, agent working memory) and Neo4j (counterparty graph).
Each can run either inside Kubernetes or as an AWS managed service.

## Options

| | **In the cluster** (chosen) | **AWS managed services** |
|---|---|---|
| Postgres + pgvector | CloudNativePG operator | Amazon RDS for PostgreSQL (supports pgvector) |
| OpenSearch | Official Helm chart, single node | Amazon OpenSearch Service |
| Redis | Plain StatefulSet (official image) | Amazon ElastiCache / MemoryDB |
| Neo4j | Official Helm chart | No AWS equivalent (Neo4j Aura, or Amazon Neptune with a different query language) |
| Cost | Dev machine only (~$0 extra) | Each service bills per hour, even idle |
| Same setup locally and on EKS | Yes (same Argo CD apps) | No (kind can't run RDS) |
| Operational work | Ours: upgrades, backups, failover | AWS's |
| Learning value | High: operators, StatefulSets, storage | Lower: mostly configuration |

## Decision

Run all four in the cluster, on a dedicated `workload: data` node, installed by Argo CD.

## Consequences

- **Good:** one environment definition from laptop-scale to EKS; nothing extra to pay for; every
  store is visible and debuggable with the same tools (`kubectl`, Argo CD, Prometheus).
- **Bad:** we own backups, upgrades and recovery. In kind, data lives on the dev machine's disk
  (`/var/lib/sentinel-data`), so losing that machine loses the data (mitigated: filings can be re-ingested
  from the download cache or EDGAR; reference data and trades are regenerated).
- **Phase 8 decision point:** on EKS, either keep the same apps on EBS-backed volumes, or move Postgres
  and OpenSearch to RDS / OpenSearch Service. Neo4j stays in the cluster either way. Decide then,
  with real cost numbers.
