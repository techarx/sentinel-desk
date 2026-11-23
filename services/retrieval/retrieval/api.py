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
