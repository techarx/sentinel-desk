# ADR-006: Chunking and embedding SEC filings

- **Status:** Accepted, with a known gap to measure in Phase 2
- **Date:** 2026-11-12
- **Phase:** 1

## Context

Filings are long (a 10-K section can exceed 60,000 tokens); the embedding model reads at most 512
tokens; one embedding should capture one topic; answers need precise citations.

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Sections | Items 1A, 7, 7A, 8 (10-Q items mapped to the same numbers) | Phase 2 can filter by section; chunks never mix sections |
| Section splitting | Item headings → title headings → EX-13 exhibit → "Overview" fallback | Tuned on the real filings: Citi's wrapped MD&A title, Wells Fargo's "Financial Review", BNY's untitled 10-Q MD&A |
| Chunk size | Target ~450 tokens, hard max 510 | Fits bge-small's 512-token window (2 special tokens) with room to spare |
| Cut points | Line (paragraph / table row) and sentence ends only | Never splits a sentence unless one sentence alone exceeds a chunk |
| Small tails | A final chunk under 100 tokens merges into the previous one if it fits | Avoids tiny, noisy fragments |
| Overlap | Up to ~50 tokens of whole units carried into the next chunk | Protects context at boundaries (but see the finding below) |
| Embedding model | `BAAI/bge-small-en-v1.5`, 384 dimensions, via fastembed (ONNX Runtime) on CPU | Strong small retrieval model; no GPU; ~0.7 GB image instead of ~2 GB with PyTorch |
| Model delivery | Baked into the image at build time | No downloads at run time; reproducible |
| Storage | pgvector `vector(384)` with an HNSW cosine index; same chunks in OpenSearch for BM25 | Semantic and keyword search over identical units |

Result: 60 filings → 177 sections → 19,666 chunks (average ~410 tokens, max 450).

## Finding: overlap rarely happens (found during the hands-on lab)

Overlap carries over only *whole* units that fit in 50 tokens. Units are whole paragraphs unless a
paragraph exceeds 400 tokens, and most MD&A paragraphs are 60–200 tokens. So when a chunk ends on a
paragraph (the common case in prose), **nothing is carried over**; overlap only appears when a chunk
ends on short lines such as table rows. The unit test missed this because it used one long line of
short sentences, a shape real filings rarely have.

Impact is likely modest because cuts already fall on paragraph boundaries, but it is unmeasured.

## Phase 2 experiment

Measure recall@5 and MRR on the golden question set for:

1. current chunking (overlap only when a chunk ends on short units);
2. sentence-level units, so ~50 tokens of overlap almost always applies;
3. no overlap + neighbour expansion at query time (fetch `ordinal ± 1` from the same section).

Adopt whichever measurably wins; re-chunking and re-embedding all 60 filings takes ~35 minutes from the cache.
