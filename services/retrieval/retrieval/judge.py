"""LLM-as-judge: is the answer faithful to its sources, and does it answer the question?

Faithfulness (the RAGAS idea, with a written rubric):
  1. split the answer into atomic claims (one fact each);
  2. for each claim: supported / unsupported / contradicted by the SOURCES;
  faithfulness = supported claims / all claims.
  It measures grounding, not truth: a claim copied faithfully from a wrong source still scores as supported.

Answer relevance: a 1-5 rubric score for how directly the answer addresses the question,
regardless of whether it's true; normalised to 0..1.

Judges make mistakes too. Step 2.6's lab compares these scores with your own judgment.
"""

from __future__ import annotations

from dataclasses import dataclass

from .llm import LLM
from .rag import Answer, format_sources

FAITHFULNESS_SYSTEM = """You verify whether an ANSWER is supported by its SOURCES. You do not use outside knowledge.

Steps:
1. Split the ANSWER into atomic factual claims (one fact each). Ignore citation markers like [S1].
   A statement that information is missing is not a factual claim; skip it.
2. For each claim, decide using ONLY the SOURCES:
   - "supported": stated in, or directly implied by, the sources
   - "unsupported": not in the sources (even if it may be true in the real world)
   - "contradicted": the sources say something different

Return JSON only:
{"claims": [{"claim": "...", "verdict": "supported|unsupported|contradicted", "sources": ["S1"], "reason": "..."}]}"""

RELEVANCE_SYSTEM = """You rate how well an ANSWER addresses a QUESTION. Ignore whether the answer is true;
judge only whether it responds to what was asked.

5 = directly and completely answers the question
4 = answers it, with minor gaps or some padding
3 = partially answers it
2 = mostly about something else, touches the question
1 = does not address the question (an honest "the sources don't say" scores 1 here)

Return JSON only: {"score": 1-5, "reason": "..."}"""


@dataclass
class Verdict:
    faithfulness: float | None  # None when the answer makes no factual claims
    claims: list[dict]
    relevance: float  # 0..1
    relevance_score: int  # 1..5
    relevance_reason: str


def faithfulness_score(claims: list[dict]) -> float | None:
    if not claims:
        return None
    return sum(1 for c in claims if c.get("verdict") == "supported") / len(claims)


def judge(ans: Answer, llm: LLM) -> Verdict:
    sources = format_sources(ans.sources)
    f = llm.complete_json(FAITHFULNESS_SYSTEM, f"SOURCES:\n\n{sources}\n\nANSWER:\n{ans.text}")
    claims = [c for c in f.get("claims", []) if isinstance(c, dict) and c.get("claim")]
    r = llm.complete_json(RELEVANCE_SYSTEM, f"QUESTION:\n{ans.question}\n\nANSWER:\n{ans.text}", max_tokens=300)
    score = min(5, max(1, int(r.get("score", 1))))
    return Verdict(faithfulness_score(claims), claims, (score - 1) / 4, score, str(r.get("reason", "")))
