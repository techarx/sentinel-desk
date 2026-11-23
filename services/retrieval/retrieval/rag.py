"""Retrieval-augmented generation: retrieve chunks, then have the LLM answer ONLY from them, with citations.

    question ──► Searcher (hybrid by default) ──► top-k chunks ──► numbered sources [S1]..[Sk]
                                                                        │
                                          LLM: "answer only from these, cite every sentence"
                                                                        ▼
                                                                 answer with [S#] citations
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .llm import LLM
from .models import Filters, Hit
from .search import Searcher

ANSWER_SYSTEM = """You are a research assistant for a bank's markets desk.
You answer questions about banks' SEC filings.

Rules:
- Use ONLY the numbered sources provided. Never use outside knowledge, even if you are confident.
- Cite every sentence with the source(s) it comes from, like [S1] or [S2][S4], at the end of the sentence.
- Quote figures exactly as they appear in the sources, with their units and periods.
- If the sources don't contain the answer, or only part of it, say clearly what is missing. Do not guess.
- Be concise: at most 150 words."""


@dataclass
class Answer:
    question: str
    method: str
    filters: Filters
    sources: list[Hit]
    text: str


def format_sources(hits: list[Hit]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        header = f"[S{i}] ({h.ticker} {h.fiscal_year} {h.form}, item {h.item}, chunk {h.chunk_id})"
        blocks.append(f"{header}\n{h.text.strip()}")
    return "\n\n".join(blocks)


def answer(question: str, searcher: Searcher, llm: LLM, method: str = "hybrid", k: int = 5,
           filters: Filters | None = None) -> Answer:
    filters = filters or Filters()
    hits = searcher.search(method, question, k, filters)
    if not hits:
        return Answer(question, method, filters, [], "No sources were found for this question, so I can't answer it.")
    user = f"Sources:\n\n{format_sources(hits)}\n\nQuestion: {question}"
    return Answer(question, method, filters, hits, llm.complete(ANSWER_SYSTEM, user, max_tokens=600).strip())


# A sentence ends at . ! ? followed by whitespace and a capital, digit, quote, bracket or citation
# (models sometimes put "[S1]" at the START of the next sentence instead of the end).
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[“])")
_CITATION = re.compile(r"\[S(\d+)\]")


def citation_check(text: str, n_sources: int) -> dict:
    """Deterministic (no LLM): how many sentences carry a citation, and are all citations valid?

    Markdown headings are ignored; each line is split into sentences separately.
    """
    sentences = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sentences += [s for s in _SENTENCE.split(line) if len(_CITATION.sub("", s).split()) >= 3]
    cited = [s for s in sentences if _CITATION.search(s)]
    numbers = [int(n) for n in _CITATION.findall(text)]
    return {
        "sentences": len(sentences),
        "cited_sentences": len(cited),
        "coverage": (len(cited) / len(sentences)) if sentences else 1.0,
        "invalid_citations": sorted({n for n in numbers if not 1 <= n <= n_sources}),
        "sources_used": sorted({n for n in numbers if 1 <= n <= n_sources}),
    }
