"""The trade event, and how it is written to / read from the Redis stream.

Redis stream entries are flat string maps, so every field is a string on the
wire; Trade.to_fields / Trade.from_fields convert both ways.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

STREAM = "trades"
GROUP = "exposure"
SIDES = ("BUY", "SELL")


@dataclass(frozen=True)
class Trade:
    trade_id: str  # UUID; makes processing idempotent
    ts: datetime  # event time (timezone-aware, UTC)
    desk_id: int
    book_id: int
    counterparty_id: int
    asset_class: str
    instrument: str
    side: str
    notional: Decimal
    ccy: str
    trader: str

    @property
    def signed_notional(self) -> Decimal:
        """Buys add to net exposure, sells subtract."""
        return self.notional if self.side == "BUY" else -self.notional

    def to_fields(self) -> dict[str, str]:
        return {
            "trade_id": self.trade_id,
            "ts": self.ts.isoformat(),
            "desk_id": str(self.desk_id),
            "book_id": str(self.book_id),
            "counterparty_id": str(self.counterparty_id),
            "asset_class": self.asset_class,
            "instrument": self.instrument,
            "side": self.side,
            "notional": str(self.notional),
            "ccy": self.ccy,
            "trader": self.trader,
        }

    @classmethod
    def from_fields(cls, fields: dict) -> Trade:
        f = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
             for k, v in fields.items()}
        side = f["side"]
        if side not in SIDES:
            raise ValueError(f"bad side {side!r}")
        return cls(
            trade_id=f["trade_id"],
            ts=datetime.fromisoformat(f["ts"]),
            desk_id=int(f["desk_id"]),
            book_id=int(f["book_id"]),
            counterparty_id=int(f["counterparty_id"]),
            asset_class=f["asset_class"],
            instrument=f["instrument"],
            side=side,
            notional=Decimal(f["notional"]),
            ccy=f["ccy"],
            trader=f["trader"],
        )


@dataclass
class ExposureDelta:
    gross: Decimal = Decimal(0)
    net: Decimal = Decimal(0)
    trade_count: int = 0
    last_trade_at: datetime | None = None


def exposure_deltas(trades: list[Trade]) -> dict[tuple[int, int], ExposureDelta]:
    """Sum a batch of trades per (desk, counterparty): what each exposures row changes by."""
    deltas: dict[tuple[int, int], ExposureDelta] = {}
    for t in trades:
        d = deltas.setdefault((t.desk_id, t.counterparty_id), ExposureDelta())
        d.gross += t.notional
        d.net += t.signed_notional
        d.trade_count += 1
        d.last_trade_at = t.ts if d.last_trade_at is None else max(d.last_trade_at, t.ts)
    return deltas
