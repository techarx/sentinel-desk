# services/retrieval — vector, keyword and hybrid search

Searches the 19,666 filing chunks loaded in Phase 1, three ways:

| Method | How | Good at |
|---|---|---|
| `vector` | Embed the question with bge-small (plus its query instruction), nearest chunks in pgvector (HNSW, cosine) | Meaning and paraphrase |
| `bm25` | Keyword match in OpenSearch's `chunks` index | Exact terms, names, acronyms, numbers |
| `hybrid` | Top 50 from each, merged with Reciprocal Rank Fusion (`fusion.py`) | Both: chunks that either list ranks well, or both rank moderately |

Filters on all methods: ticker, fiscal year, form (10-K / 10-Q), item (1A, 7, 7A, 8).

## Use

On the dev machine:

```bash
make search Q="How did deposit costs affect net interest income?"
make search Q="CET1 ratio" TICKER=PNC YEAR=2025 METHOD=bm25 K=10
make search Q="credit card charge-offs" NO_INSTRUCTION=1     # vector search without the bge query instruction
```

In the cluster (agents, Phase 3): `GET http://retrieval.data.svc:8000/search?q=...&method=hybrid&k=5&ticker=BAC,WFC`.

## Details worth knowing

- **Query instruction.** bge models embed questions with `Represent this sentence for searching relevant passages: ` in
  front and passages without it. The service adds it; `--no-instruction` turns it off so you can compare.
- **HNSW + filters.** pgvector's index is approximate. `hnsw.ef_search = 100` (default 40) checks more candidates;
  `hnsw.iterative_scan = relaxed_order` keeps searching when filters discard results, so filtered queries still
  return k hits.
- **Least privilege.** Postgres as `readonly_analyst` (no writes, no PII columns). OpenSearch still uses `admin`;
  a read-only user comes in Phase 5.
- **Fusion uses ranks, not scores.** Cosine similarity (0–1) and BM25 (0–∞) aren't comparable; RRF sidesteps that.
