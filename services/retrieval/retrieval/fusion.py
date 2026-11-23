"""Reciprocal Rank Fusion (RRF): merge ranked lists into one.

Each list votes for its items with 1 / (K + rank). An item ranked high in
either list, or moderately high in both, ends up near the top. Only ranks
are used, never raw scores, which is why RRF works for combining a cosine
similarity (0..1) with a BM25 score (0..anything) without any tuning.

K = 60 is the value from the original paper (Cormack et al., 2009); it keeps
a single first place from dominating everything else.
"""

from __future__ import annotations

from collections.abc import Sequence

from .models import Hit

RRF_K = 60


def rrf(lists: dict[str, Sequence[Hit]], k: int, rrf_k: int = RRF_K) -> list[Hit]:
    """Fuse named ranked lists (e.g. {"vector": [...], "bm25": [...]}) and return the top k."""
    scores: dict[int, float] = {}
    by_id: dict[int, Hit] = {}
    ranks: dict[int, dict[str, int | None]] = {}
    for name, hits in lists.items():
        for rank, hit in enumerate(hits, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (rrf_k + rank)
            by_id.setdefault(hit.chunk_id, hit)
            ranks.setdefault(hit.chunk_id, dict.fromkeys(lists))[name] = rank

    fused = []
    for chunk_id in sorted(scores, key=lambda c: scores[c], reverse=True)[:k]:
        base = by_id[chunk_id]
        fused.append(Hit(base.chunk_id, scores[chunk_id], base.ticker, base.fiscal_year, base.form,
                         base.item, base.text, ranks=ranks[chunk_id]))
    return fused
