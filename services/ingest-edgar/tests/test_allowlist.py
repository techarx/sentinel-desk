from pathlib import Path

import pytest

from ingest_edgar.config import allowed_tickers, banks, check_allowed

ENTITIES = Path(__file__).resolve().parents[3] / "config" / "entities.yaml"


def test_allowlist_has_the_ten_banks():
    assert allowed_tickers(ENTITIES) == ["BAC", "C", "WFC", "GS", "MS", "USB", "PNC", "TFC", "COF", "BNY"]


def test_every_bank_has_a_10_digit_cik():
    for ticker, (cik, _name) in banks(ENTITIES).items():
        assert len(cik) == 10 and cik.isdigit(), ticker


def test_allowed_tickers_pass_and_are_normalised():
    assert check_allowed(["bac", "WFC"], allowed_tickers(ENTITIES)) == ["BAC", "WFC"]


def test_anything_not_allowlisted_is_refused():
    with pytest.raises(ValueError, match="Not in the allowlist"):
        check_allowed(["BAC", "XYZ"], allowed_tickers(ENTITIES))
