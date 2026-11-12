"""Publish synthetic trades to the Redis stream at a steady rate, with bursts.

- Rate: TRADE_RATE per second (default 100). Every 2 minutes, a 10-second burst at 3x.
- Counterparty activity is skewed (a few counterparties trade most), like real books.
- The stream is capped (approximately MAX_STREAM_LEN entries) so Redis memory stays
  bounded; the consumer keeps up long before entries are trimmed.
"""

from __future__ import annotations

import logging
import math
import random
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from prometheus_client import Counter

from . import refdata
from .model import STREAM, Trade

log = logging.getLogger(__name__)

PRODUCED = Counter("trades_produced", "Trades published to the Redis stream")
MAX_STREAM_LEN = 200_000
TICK_SECONDS = 0.1
BURST_EVERY_S, BURST_LENGTH_S, BURST_FACTOR = 120, 10, 3


@dataclass(frozen=True)
class RefData:
    desks: list[tuple[int, str]]  # (desk_id, asset_class)
    books: dict[int, list[int]]  # desk_id -> book ids
    counterparties: list[int]
    cp_weights: list[float]


def load_refdata(conn, seed: int = 7) -> RefData:
    asset_class = {name: ac for name, _region, ac in refdata.DESKS}
    desks = [(i, asset_class[n]) for i, n in conn.execute("SELECT id, name FROM desks ORDER BY id").fetchall()]
    books: dict[int, list[int]] = {}
    for book_id, desk_id in conn.execute("SELECT id, desk_id FROM books ORDER BY id").fetchall():
        books.setdefault(desk_id, []).append(book_id)
    cps = [row[0] for row in conn.execute("SELECT id FROM counterparties ORDER BY id").fetchall()]
    if not desks or not cps:
        raise RuntimeError("No reference data: has the seed job run?")
    # Zipf-like skew: the k-th most active counterparty trades ~1/k^1.1 as often.
    order = cps[:]
    random.Random(seed).shuffle(order)
    rank = {cp: i + 1 for i, cp in enumerate(order)}
    return RefData(desks, books, cps, [1 / rank[c] ** 1.1 for c in cps])


def make_trade(ref: RefData, rng: random.Random, now: datetime) -> Trade:
    desk_id, asset_class = rng.choice(ref.desks)
    instrument, ccy = rng.choice(list(refdata.INSTRUMENTS[asset_class].items()))
    # Log-normal sizes: median ~$10M, from $100k up to $500M, rounded to $1,000.
    notional = min(max(math.exp(rng.gauss(math.log(10_000_000), 1.0)), 100_000), 500_000_000)
    return Trade(
        trade_id=str(uuid.UUID(int=rng.getrandbits(128), version=4)),
        ts=now,
        desk_id=desk_id,
        book_id=rng.choice(ref.books[desk_id]),
        counterparty_id=rng.choices(ref.counterparties, weights=ref.cp_weights)[0],
        asset_class=asset_class,
        instrument=instrument,
        side=rng.choice(("BUY", "SELL")),
        notional=Decimal(round(notional, -3)).quantize(Decimal("1.00")),
        ccy=ccy,
        trader=f"TR{desk_id:02d}{rng.randint(1, 12):02d}",  # trader IDs, not names
    )


def rate_at(elapsed: float, base_rate: float, bursts: bool) -> float:
    if bursts and elapsed % BURST_EVERY_S >= BURST_EVERY_S - BURST_LENGTH_S:
        return base_rate * BURST_FACTOR
    return base_rate


def run(
    redis_client, ref: RefData, rate: float, duration: float = 0, bursts: bool = True, seed: int | None = None
) -> int:
    """Publish until `duration` seconds have passed (0 = forever). Returns trades published."""
    rng = random.Random(seed)
    start = time.monotonic()
    published = 0.0  # fractional "owed" trades carry over between ticks
    sent = 0
    log.info("Publishing ~%s trades/s to stream %r%s", rate, STREAM, " with bursts" if bursts else "")
    while duration <= 0 or time.monotonic() - start < duration:
        tick_start = time.monotonic()
        published += rate_at(tick_start - start, rate, bursts) * TICK_SECONDS
        n = int(published)
        published -= n
        if n:
            now = datetime.now(UTC)
            pipe = redis_client.pipeline(transaction=False)
            for _ in range(n):
                pipe.xadd(STREAM, make_trade(ref, rng, now).to_fields(), maxlen=MAX_STREAM_LEN, approximate=True)
            pipe.execute()
            PRODUCED.inc(n)
            sent += n
        time.sleep(max(0.0, TICK_SECONDS - (time.monotonic() - tick_start)))
    log.info("Published %s trades", sent)
    return sent
