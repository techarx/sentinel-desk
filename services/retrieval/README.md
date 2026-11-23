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

## Answers with citations, and judging them (Step 2.6)

```bash
make ask Q="How did lower funding costs affect PNC's net interest income in 2025?" TICKER=PNC YEAR=2025 ITEM=7
```

1. **Retrieve** (hybrid by default) the top-k chunks, numbered `[S1]..[Sk]`.
2. **Answer** with Claude on Bedrock (`rag.py`): only from the sources, every sentence cited, say what's missing.
3. **Check** the answer:
   - *Citations* (`rag.citation_check`, no LLM): share of sentences with a citation; citations to sources that don't exist.
   - *Faithfulness* (`judge.py`, LLM judge): the answer is split into atomic claims; each is supported / unsupported /
     contradicted by the sources. Score = supported / all. Measures grounding, not truth.
   - *Answer relevance* (LLM judge): 1–5 rubric for how directly it answers the question.

API: `GET /ask?q=...&ticker=PNC&judge=true`. Every call costs LLM tokens (~1 cent for answer + judge with Haiku 4.5).

**Credentials:** pods never hold AWS keys. The dev machine assumes the IAM role `sentinel-bedrock-invoker` (only the
allowlisted models, via `us.` inference profiles) every 20 minutes and writes 1-hour credentials to the Secret
`bedrock-credentials`; the SDK reads them through `credential_process` (`deploy/apps/retrieval/aws-config.yaml`).
Install once on the dev machine: `make bedrock-creds-install`; check: `make bedrock-creds-status`.

**Model:** `LLM_MODEL_ID` in `deploy/apps/retrieval/deployment.yaml` (default Claude Haiku 4.5). Newer Claude models need
an account admin to complete Bedrock's one-time Marketplace subscription; `global.` profiles are blocked by account policy.

## Details worth knowing

- **Query instruction.** bge models embed questions with `Represent this sentence for searching relevant passages: ` in
  front and passages without it. The service adds it; `--no-instruction` turns it off so you can compare.
- **HNSW + filters.** pgvector's index is approximate. `hnsw.ef_search = 100` (default 40) checks more candidates;
  `hnsw.iterative_scan = relaxed_order` keeps searching when filters discard results, so filtered queries still
  return k hits.
- **Least privilege.** Postgres as `readonly_analyst` (no writes, no PII columns). OpenSearch still uses `admin`;
  a read-only user comes in Phase 5.
- **Fusion uses ranks, not scores.** Cosine similarity (0–1) and BM25 (0–∞) aren't comparable; RRF sidesteps that.
