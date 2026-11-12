# services/trades — reference data, trade generator, trade consumer

One image, three commands (`python -m trades <command>`):

| Command | Runs as | What it does |
|---|---|---|
| `seed` | Argo CD sync hook (Job) | Desks, books, counterparties (GLEIF subsidiaries of the allowlisted banks + fictional ones), customers → Postgres; banks, desks, counterparties and `SUBSIDIARY_OF` links → Neo4j. Idempotent. |
| `generate` | Deployment `trade-generator` (off by default) | ~100 synthetic trades/s to the Redis stream `trades`, with a 3x burst for 10 s every 2 min. Skewed counterparty activity. |
| `consume` | Deployment `trade-consumer` | Reads the stream as consumer group `exposure`; stores trades, upserts `exposures`, mirrors them as `TRADES_WITH` edges in Neo4j. |

```
trade-generator ──XADD──► Redis stream "trades" ──XREADGROUP──► trade-consumer
                                                                   ├─► Postgres: trades (insert-once), exposures (upsert)
                                                                   ├─► Neo4j: (Desk)-[:TRADES_WITH {gross, net, ...}]->(Counterparty)
                                                                   └─► XACK
```

## Exactly-once *effects* on an at-least-once stream

Redis redelivers anything not acknowledged (crash, restart), so the consumer is idempotent:

1. `INSERT trades ... ON CONFLICT (trade_id) DO NOTHING RETURNING trade_id`: only first-time trades come back.
2. Exposures are upserted from **those new trades only**, in the same transaction.
3. Neo4j edges are **overwritten** (`SET`) with the totals read back from Postgres, never incremented, so a retry after a
   Neo4j failure writes the same correct values.
4. `XACK` only after both writes.

`scripts/trades-test.sh` proves it: it re-publishes trades with the same IDs and checks nothing is counted twice.

## Least privilege

| Process | Postgres role | Can |
|---|---|---|
| seed | `sentinel` (schema owner) | write reference data |
| generator | `trade_generator` | read desks, books, counterparties |
| consumer | `stream_writer` | insert trades, upsert exposures; no PII, no filings |

## Operating it (dev machine)

```bash
make stream-start    # generator on (~100 trades/s)
make stream-status   # backlog, trades/s and lag over the last minute
make stream-stop     # generator off; the consumer drains the rest
make trades-test     # integration test against throwaway containers (same as CI)
```

Metrics on `:9100/metrics` (scraped by Prometheus): `trades_produced_total`, `trades_consumed_total{result}`,
`trade_event_lag_seconds`, `trade_consumer_batch_seconds`, `trade_stream_group_lag`, `trade_stream_pending`.
