"""The three search methods.

- vector: embed the question with bge-small, find the nearest chunk embeddings in pgvector.
- bm25:   keyword search over the same chunks in OpenSearch.
- hybrid: both, fused with Reciprocal Rank Fusion (fusion.py).
"""

from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path

import psycopg
from opensearchpy import OpenSearch

from .fusion import rrf
from .models import Filters, Hit

MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/models"))
INDEX = "chunks"

# bge models are trained to embed a search QUERY with this instruction in front,
# and the PASSAGES (our chunks) without it. Leaving it out makes vector search worse.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

CANDIDATES = 50  # how many each method contributes before fusion (see the recall@50 discussion)


class Searcher:
    def __init__(self, use_query_instruction: bool = True):
        self.use_query_instruction = use_query_instruction

    # -- connections (opened on first use) -----------------------------------

    @cached_property
    def _pg(self) -> psycopg.Connection:
        conn = psycopg.connect("", autocommit=True)  # PG* env vars; read-only role in the cluster
        # HNSW is approximate: ef_search trades speed for accuracy (default 40).
        # iterative_scan keeps searching when filters remove candidates, so a
        # filtered query still returns k results (pgvector >= 0.8).
        conn.execute("SET hnsw.ef_search = 100")
        conn.execute("SET hnsw.iterative_scan = relaxed_order")
        return conn

    @cached_property
    def _os(self) -> OpenSearch:
        return OpenSearch(
            hosts=[os.environ.get("OPENSEARCH_URL", "https://opensearch-cluster-master:9200")],
            http_auth=(os.environ.get("OPENSEARCH_USER", "admin"), os.environ["OPENSEARCH_PASSWORD"]),
            verify_certs=False,  # self-signed demo certificate; Istio mTLS in Phase 5
            ssl_show_warn=False,
            timeout=30,
        )

    @cached_property
    def _model(self):
        from fastembed import TextEmbedding  # heavy import, only when vector search is used

        return TextEmbedding(MODEL_NAME, cache_dir=str(MODEL_DIR))

    def embed_query(self, question: str) -> list[float]:
        text = QUERY_INSTRUCTION + question if self.use_query_instruction else question
        return next(iter(self._model.embed([text]))).tolist()

    # -- methods ---------------------------------------------------------------

    def vector(self, question: str, k: int = 5, filters: Filters | None = None) -> list[Hit]:
        vec = "[" + ",".join(f"{x:.7f}" for x in self.embed_query(question)) + "]"
        where, params = _sql_filters(filters or Filters())
        rows = self._pg.execute(
            f"""SELECT c.id, 1 - (e.embedding <=> %s::vector) AS similarity,
                       c.ticker, c.fiscal_year, c.form, c.item, c.text
                  FROM chunk_embeddings e JOIN chunks c ON c.id = e.chunk_id
                 {where}
                 ORDER BY e.embedding <=> %s::vector
                 LIMIT %s""",
            [vec, *params, vec, k],
        ).fetchall()
        return [Hit(r[0], float(r[1]), r[2], r[3], r[4], r[5], r[6]) for r in rows]

    def bm25(self, question: str, k: int = 5, filters: Filters | None = None) -> list[Hit]:
        body = {
            "size": k,
            "_source": ["chunk_id", "ticker", "fiscal_year", "form", "item", "text"],
            "query": {"bool": {"must": {"match": {"text": question}}, "filter": _os_filters(filters or Filters())}},
        }
        hits = self._os.search(index=INDEX, body=body)["hits"]["hits"]
        return [
            Hit(int(h["_id"]), float(h["_score"]), s["ticker"], s["fiscal_year"], s["form"], s["item"], s["text"])
            for h in hits
            for s in [h["_source"]]
        ]

    def hybrid(self, question: str, k: int = 5, filters: Filters | None = None,
               candidates: int = CANDIDATES) -> list[Hit]:
        return rrf({"vector": self.vector(question, candidates, filters),
                    "bm25": self.bm25(question, candidates, filters)}, k)

    def search(self, method: str, question: str, k: int = 5, filters: Filters | None = None) -> list[Hit]:
        if method not in ("vector", "bm25", "hybrid"):
            raise ValueError(f"unknown method {method!r}")
        return getattr(self, method)(question, k, filters)


def _sql_filters(f: Filters) -> tuple[str, list]:
    clauses, params = [], []
    for column, values in (("c.ticker", f.tickers), ("c.fiscal_year", f.years),
                           ("c.form", f.forms), ("c.item", f.items)):
        if values:
            clauses.append(f"{column} = ANY(%s)")
            params.append(list(values))
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def _os_filters(f: Filters) -> list[dict]:
    return [{"terms": {field: list(values)}}
            for field, values in (("ticker", f.tickers), ("fiscal_year", f.years),
                                  ("form", f.forms), ("item", f.items)) if values]
