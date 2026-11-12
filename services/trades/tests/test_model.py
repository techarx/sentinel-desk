from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trades.model import Trade, exposure_deltas

T0 = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def trade(i: int, desk: int = 1, cp: int = 7, side: str = "BUY", notional: str = "1000000.00", dt: int = 0) -> Trade:
    return Trade(f"00000000-0000-4000-8000-{i:012d}", T0 + timedelta(seconds=dt), desk, 10, cp,
                 "rates", "UST 10Y", side, Decimal(notional), "USD", "TR0101")


def test_round_trip_through_stream_fields():
    t = trade(1)
    wire = {k.encode(): v.encode() for k, v in t.to_fields().items()}  # what redis-py returns
    assert Trade.from_fields(wire) == t


def test_bad_side_is_rejected():
    fields = trade(1).to_fields() | {"side": "HOLD"}
    with pytest.raises(ValueError):
        Trade.from_fields(fields)


def test_exposure_deltas_sum_per_desk_and_counterparty():
    deltas = exposure_deltas([
        trade(1, notional="5000000"),
        trade(2, notional="3000000", side="SELL", dt=5),
        trade(3, desk=2, notional="2000000"),
    ])
    assert set(deltas) == {(1, 7), (2, 7)}
    d = deltas[(1, 7)]
    assert d.gross == Decimal("8000000")
    assert d.net == Decimal("2000000")  # 5M buy - 3M sell
    assert d.trade_count == 2
    assert d.last_trade_at == T0 + timedelta(seconds=5)
