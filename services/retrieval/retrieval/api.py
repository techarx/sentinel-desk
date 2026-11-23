"""HTTP API. Agents (Phase 3) call this instead of talking to Postgres and OpenSearch directly.

GET /search?q=...&method=hybrid&k=5&ticker=BAC,WFC&year=2025&form=10-K&item=7
GET /healthz
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query

from .models import Filters
from .search import Searcher

app = FastAPI(title="Sentinel Desk retrieval")
searcher = Searcher()


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/search")
def search(
    q: str = Query(..., min_length=2),
    method: str = "hybrid",
    k: int = Query(5, ge=1, le=50),
    ticker: str = "",
    year: str = "",
    form: str = "",
    item: str = "",
) -> dict:
    if method not in ("vector", "bm25", "hybrid"):
        raise HTTPException(400, "method must be vector, bm25 or hybrid")
    filters = Filters.parse(ticker, year, form, item)
    hits = searcher.search(method, q, k, filters)
    return {"question": q, "method": method, "filters": filters.describe(), "hits": [asdict(h) for h in hits]}


@app.get("/ask")
def ask(
    q: str = Query(..., min_length=2),
    method: str = "hybrid",
    k: int = Query(5, ge=1, le=20),
    ticker: str = "",
    year: str = "",
    form: str = "",
    item: str = "",
    judge_answer: bool = Query(False, alias="judge"),
) -> dict:
    """Retrieve, answer with citations, optionally judge. Each call costs LLM tokens."""
    from .judge import judge
    from .llm import LLM
    from .rag import answer, citation_check

    if method not in ("vector", "bm25", "hybrid"):
        raise HTTPException(400, "method must be vector, bm25 or hybrid")
    llm = LLM()
    ans = answer(q, searcher, llm, method, k, Filters.parse(ticker, year, form, item))
    result = {
        "question": q,
        "answer": ans.text,
        "sources": [{"ref": f"S{i}", "chunk_id": h.chunk_id, "label": h.label()} for i, h in enumerate(ans.sources, 1)],
        "citations": citation_check(ans.text, len(ans.sources)),
    }
    if judge_answer and ans.sources:
        v = judge(ans, llm)
        result["judge"] = {"faithfulness": v.faithfulness, "claims": v.claims,
                           "relevance": v.relevance, "relevance_reason": v.relevance_reason}
    result["usage"] = {"input_tokens": llm.usage.input_tokens, "output_tokens": llm.usage.output_tokens,
                       "cost_usd": llm.usage.cost_usd()}
    return result
