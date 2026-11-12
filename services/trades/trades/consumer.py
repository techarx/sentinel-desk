"""Consume trades from the Redis stream; keep exposures (Postgres) and the
desk -> counterparty graph (Neo4j) current.

Delivery is at-least-once (a crash before XACK means redelivery), so every
step is idempotent:

1. INSERT trades ... ON CONFLICT (trade_id) DO NOTHING RETURNING trade_id
   -> only trades seen for the first time come back.
2. Upsert exposures using ONLY those new trades, in the same transaction,
   so a redelivered trade can never be counted twice.
3. Copy the resulting exposure rows to Neo4j with SET (overwrite), not an
   increment: if Neo4j fails after Postgres committed, the retry writes the
   same correct totals again instead of double-counting or missing them.
4. XACK only after both writes succeeded.

Postgres is the source of truth; Neo4j holds a copy shaped for graph queries.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from datetime import UTC, datetime

import redis
from prometheus_client import Counter, Gauge, Histogram

from .model import GROUP, STREAM, Trade, exposure_deltas

log = logging.getLogger(__name__)

CONSUMED = Counter("trades_consumed", "Trades processed", ["result"])  # result: new | duplicate
ERRORS = Counter("trade_consumer_errors", "Batches that failed and will be retried")
EVENT_LAG = Histogram(
    "trade_event_lag_seconds", "Now minus trade event time when the trade is committed",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 300),
)
BATCH_SECONDS = Histogram("trade_consumer_batch_seconds", "Time to process one batch",
                          buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5))
GROUP_LAG = Gauge("trade_stream_group_lag", "Stream entries not yet delivered to the consumer group")
PENDING = Gauge("trade_stream_pending", "Entries delivered but not yet acknowledged")

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "500"))
BLOCK_MS = 1000
RECLAIM_IDLE_MS = 60_000


def ensure_group(r: redis.Redis) -> None:
    try:
        r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        log.info("Created consumer group %r on stream %r", GROUP, STREAM)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def write_batch(conn, driver, trades: list[Trade]) -> int:
    """Steps 1-3. Returns how many trades were new."""
    with conn.transaction():
        new_ids = {
            row[0]
            for row in conn.execute(
                """INSERT INTO trades (trade_id, ts, desk_id, book_id, counterparty_id, asset_class,
                                       instrument, side, notional, ccy, trader)
                   SELECT * FROM unnest(%s::uuid[], %s::timestamptz[], %s::smallint[], %s::int[], %s::bigint[],
                                        %s::text[], %s::text[], %s::text[], %s::numeric[], %s::text[], %s::text[])
                   ON CONFLICT (trade_id) DO NOTHING
                   RETURNING trade_id::text""",
                (
                    [t.trade_id for t in trades], [t.ts for t in trades], [t.desk_id for t in trades],
                    [t.book_id for t in trades], [t.counterparty_id for t in trades],
                    [t.asset_class for t in trades], [t.instrument for t in trades], [t.side for t in trades],
                    [t.notional for t in trades], [t.ccy for t in trades], [t.trader for t in trades],
                ),
            ).fetchall()
        }
        deltas = exposure_deltas([t for t in trades if t.trade_id in new_ids])
        if deltas:
            keys = list(deltas)
            conn.execute(
                """INSERT INTO exposures (desk_id, counterparty_id, gross, net, trade_count, last_trade_at, updated_at)
                   SELECT d, c, g, n, k, l, now()
                     FROM unnest(%s::smallint[], %s::bigint[], %s::numeric[], %s::numeric[], %s::bigint[],
                                 %s::timestamptz[]) AS u(d, c, g, n, k, l)
                   ON CONFLICT (desk_id, counterparty_id) DO UPDATE SET
                       gross = exposures.gross + EXCLUDED.gross,
                       net = exposures.net + EXCLUDED.net,
                       trade_count = exposures.trade_count + EXCLUDED.trade_count,
                       last_trade_at = greatest(exposures.last_trade_at, EXCLUDED.last_trade_at),
                       updated_at = now()""",
                (
                    [k[0] for k in keys], [k[1] for k in keys], [deltas[k].gross for k in keys],
                    [deltas[k].net for k in keys], [deltas[k].trade_count for k in keys],
                    [deltas[k].last_trade_at for k in keys],
                ),
            )

    # Step 3: every pair touched by the batch (new or redelivered), read back from Postgres.
    pairs = sorted({(t.desk_id, t.counterparty_id) for t in trades})
    rows = conn.execute(
        """SELECT e.desk_id, e.counterparty_id, e.gross, e.net, e.trade_count, e.last_trade_at
             FROM exposures e
             JOIN unnest(%s::smallint[], %s::bigint[]) AS p(d, c) ON e.desk_id = p.d AND e.counterparty_id = p.c""",
        ([p[0] for p in pairs], [p[1] for p in pairs]),
    ).fetchall()
    with driver.session() as s:
        s.run(
            """UNWIND $rows AS r
               MERGE (d:Desk {id: r.desk_id})
               MERGE (c:Counterparty {id: r.counterparty_id})
               MERGE (d)-[t:TRADES_WITH]->(c)
               SET t.gross = r.gross, t.net = r.net, t.trade_count = r.trade_count,
                   t.last_trade_at = datetime(r.last_trade_at), t.updated_at = datetime()""",
            rows=[
                {"desk_id": d, "counterparty_id": c, "gross": float(g), "net": float(n), "trade_count": k,
                 "last_trade_at": last.isoformat()}
                for d, c, g, n, k, last in rows
            ],
        )

    now = datetime.now(UTC)
    for t in trades:
        if t.trade_id in new_ids:
            EVENT_LAG.observe((now - t.ts).total_seconds())
    CONSUMED.labels("new").inc(len(new_ids))
    CONSUMED.labels("duplicate").inc(len(trades) - len(new_ids))
    return len(new_ids)


def _update_group_metrics(r: redis.Redis) -> None:
    for g in r.xinfo_groups(STREAM):
        name = g["name"].decode() if isinstance(g["name"], bytes) else g["name"]
        if name == GROUP:
            GROUP_LAG.set(g.get("lag") or 0)
            PENDING.set(g.get("pending") or 0)


def run(r: redis.Redis, conn, driver, exit_when_idle: float = 0) -> int:
    """Consume until stopped (or until idle for `exit_when_idle` seconds, for tests). Returns new trades."""
    ensure_group(r)
    me = os.environ.get("HOSTNAME") or socket.gethostname()
    total_new = 0
    idle_since = time.monotonic()
    last_metrics = 0.0
    # First our own unacknowledged entries ("0"), then new ones (">").
    cursor = "0"
    while True:
        if time.monotonic() - last_metrics > 5:
            _update_group_metrics(r)
            last_metrics = time.monotonic()

        # Take over entries another (crashed) consumer left unacknowledged.
        _next, claimed, *_ = r.xautoclaim(STREAM, GROUP, me, min_idle_time=RECLAIM_IDLE_MS, start_id="0-0",
                                          count=BATCH_SIZE)
        entries = claimed
        if not entries:
            resp = r.xreadgroup(GROUP, me, {STREAM: cursor}, count=BATCH_SIZE, block=BLOCK_MS)
            entries = resp[0][1] if resp else []
            if cursor == "0" and not entries:
                cursor = ">"  # backlog of our own pending entries is done
                continue

        # A pending entry whose data was already trimmed from the stream comes back
        # without fields: nothing to process, so acknowledge it to clear it.
        trimmed = [entry_id for entry_id, fields in entries if not fields]
        if trimmed:
            r.xack(STREAM, GROUP, *trimmed)
        entries = [(entry_id, fields) for entry_id, fields in entries if fields]
        if not entries:
            if exit_when_idle and time.monotonic() - idle_since > exit_when_idle:
                _update_group_metrics(r)
                return total_new
            continue
        idle_since = time.monotonic()

        started = time.monotonic()
        try:
            trades = [Trade.from_fields(fields) for _id, fields in entries]
            total_new += write_batch(conn, driver, trades)
            r.xack(STREAM, GROUP, *[entry_id for entry_id, _ in entries])
        except Exception:
            ERRORS.inc()
            log.exception("Batch of %s failed; it stays pending and will be retried", len(entries))
            time.sleep(2)
            cursor = "0"  # re-read our pending entries
            continue
        BATCH_SECONDS.observe(time.monotonic() - started)
