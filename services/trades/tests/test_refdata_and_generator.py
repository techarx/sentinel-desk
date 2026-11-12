import random
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trades import generator, refdata

ENTITIES = refdata.load_entities(Path(__file__).resolve().parents[3] / "config" / "entities.yaml")


def test_fictional_counterparties_are_deterministic_and_unique():
    first = refdata.fictional_counterparties(ENTITIES)
    assert first == refdata.fictional_counterparties(ENTITIES)
    assert len(first) == ENTITIES["counterparties"]["fictional"]["count"]
    assert len({c.name for c in first}) == len(first)
    assert all(c.is_fictional and c.lei is None for c in first)


def test_real_counterparty_must_belong_to_an_allowlisted_bank():
    bac = refdata.banks(ENTITIES)[0]
    ok = refdata.Counterparty("Sub", "bank_subsidiary", "US", False, "X" * 20, bac.lei, bac.ticker)
    refdata.check_allowlisted([ok], ENTITIES)
    stranger = refdata.Counterparty("Other", "bank_subsidiary", "US", False, "Y" * 20, "Z" * 20, "ZZZ")
    with pytest.raises(ValueError, match="not a subsidiary of an allowlisted bank"):
        refdata.check_allowlisted([stranger], ENTITIES)


def test_every_desk_has_instruments():
    for _name, _region, asset_class in refdata.DESKS:
        assert refdata.INSTRUMENTS[asset_class]


REF = generator.RefData(
    desks=[(1, "rates"), (2, "fx")],
    books={1: [10, 11], 2: [20]},
    counterparties=list(range(100, 150)),
    cp_weights=[1 / (i + 1) ** 1.1 for i in range(50)],
)


def test_generated_trades_are_valid_and_consistent():
    rng = random.Random(1)
    now = datetime.now(UTC)
    for _ in range(500):
        t = generator.make_trade(REF, rng, now)
        assert t.book_id in REF.books[t.desk_id]
        assert t.instrument in refdata.INSTRUMENTS[t.asset_class]
        assert t.side in ("BUY", "SELL")
        assert 100_000 <= t.notional <= 500_000_000


def test_counterparty_activity_is_skewed():
    rng = random.Random(2)
    now = datetime.now(UTC)
    counts = Counter(generator.make_trade(REF, rng, now).counterparty_id for _ in range(5000))
    top, *_ = counts.most_common(5)
    assert top[1] > 5 * (5000 / 50)  # busiest counterparty trades far more than an even share


def test_bursts_triple_the_rate_for_ten_seconds_every_two_minutes():
    assert generator.rate_at(5, 100, bursts=True) == 100
    assert generator.rate_at(115, 100, bursts=True) == 300
    assert generator.rate_at(115, 100, bursts=False) == 100
