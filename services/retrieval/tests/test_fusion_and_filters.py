import pytest

from retrieval.fusion import RRF_K, rrf
from retrieval.models import Filters, Hit
from retrieval.search import _os_filters, _sql_filters


def hits(*ids: int) -> list[Hit]:
    return [Hit(i, 0.0, "BAC", 2025, "10-K", "7", f"text {i}") for i in ids]


def test_rrf_rewards_items_both_lists_like():
    # 3 is only 3rd in each list, but appears in both; 1 and 5 top one list each.
    fused = rrf({"vector": hits(1, 2, 3), "bm25": hits(5, 4, 3)}, k=5)
    assert fused[0].chunk_id == 3
    assert fused[0].score == pytest.approx(2 / (RRF_K + 3))


def test_rrf_records_rank_in_each_list():
    fused = rrf({"vector": hits(1, 2), "bm25": hits(2, 9)}, k=3)
    by_id = {h.chunk_id: h.ranks for h in fused}
    assert by_id[2] == {"vector": 2, "bm25": 1}
    assert by_id[1] == {"vector": 1, "bm25": None}
    assert by_id[9] == {"vector": None, "bm25": 2}


def test_rrf_returns_at_most_k():
    assert len(rrf({"a": hits(*range(20)), "b": hits(*range(10, 30))}, k=5)) == 5


def test_filters_parse_and_normalise():
    f = Filters.parse(tickers="bac, wfc", years="2025", forms="10-k", items="7a")
    assert f == Filters(("BAC", "WFC"), (2025,), ("10-K",), ("7A",))
    assert f.describe() == "ticker=BAC,WFC year=2025 form=10-K item=7A"
    assert Filters().describe() == "none"


def test_filters_become_sql_and_opensearch_clauses():
    f = Filters(tickers=("BAC",), items=("7",))
    where, params = _sql_filters(f)
    assert where == "WHERE c.ticker = ANY(%s) AND c.item = ANY(%s)"
    assert params == [["BAC"], ["7"]]
    assert _os_filters(f) == [{"terms": {"ticker": ["BAC"]}}, {"terms": {"item": ["7"]}}]
    assert _sql_filters(Filters()) == ("", [])
