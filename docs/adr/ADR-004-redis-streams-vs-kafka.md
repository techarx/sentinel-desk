# ADR-004: Redis Streams for the trade feed, not Kafka

- **Status:** Accepted
- **Date:** 2026-11-12
- **Phase:** 1

## Context

Synthetic trades arrive at ~100 per second (3x in bursts). One consumer group turns them into
exposures (Postgres) and graph edges (Neo4j). Target: consumer lag under 5 seconds for an hour.

## Options

| | **Redis Streams** (chosen) | **Apache Kafka** |
|---|---|---|
| Already running? | Yes (also used for agent memory in Phase 3) | No: a new cluster to operate (brokers, KRaft/ZooKeeper) |
| Consumer groups, acks, redelivery | Yes (`XREADGROUP`, `XACK`, `XAUTOCLAIM`) | Yes (offsets per partition) |
| Throughput | Tens of thousands of events/s on one node | Millions/s across a cluster |
| Retention / replay | Memory-bound; we cap the stream (~200k entries) | Disk-based, days or forever; full replay |
| Ordering | One stream, totally ordered | Per partition |
| Ecosystem | Small | Large (Connect, Schema Registry, Streams) |
| Memory / ops footprint | Tiny | Large |

## Decision

Redis Streams. At 100 events/s the requirement is a durable queue with consumer groups and
redelivery, which Redis provides with a fraction of Kafka's operational weight.

## How correctness is kept without Kafka-style guarantees

Delivery is at-least-once, so the consumer makes every effect idempotent (see `services/trades/README.md`):
trades are inserted once by `trade_id`; exposures are updated only from newly inserted trades in the
same transaction; Neo4j edges are overwritten with totals read back from Postgres; `XACK` comes last.
`scripts/trades-test.sh` re-publishes trades with the same IDs and checks nothing is counted twice.

## When to switch to Kafka

- many independent consumers that each need full replay of history;
- sustained volume beyond what one Redis node handles comfortably;
- a need for long retention or an event log as the system of record.

None applies in this project.
