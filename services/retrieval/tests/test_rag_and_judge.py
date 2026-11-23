"""RAG and judge logic with a fake LLM: no Bedrock calls, no cost."""

import json

import pytest

from retrieval.judge import faithfulness_score, judge
from retrieval.llm import Usage, parse_json
from retrieval.models import Filters, Hit
from retrieval.rag import Answer, answer, citation_check, format_sources

HITS = [
    Hit(17550, 0.9, "PNC", 2025, "10-K", "7",
        "Net interest income increased $0.9 billion, or 7%, reflecting lower funding costs."),
    Hit(17549, 0.8, "PNC", 2025, "10-K", "7", "Total interest-bearing liabilities/interest expense | 2.73 | 10,897"),
]


class FakeLLM:
    """Returns queued responses and records the prompts it was given."""

    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.prompts: list[tuple[str, str]] = []
        self.usage = Usage()
        self.model_id = "fake"

    def complete(self, system: str, user: str, max_tokens: int = 800, temperature: float = 0.0) -> str:
        self.prompts.append((system, user))
        return self.responses.pop(0)

    def complete_json(self, system: str, user: str, max_tokens: int = 1500) -> dict:
        return parse_json(self.complete(system, user, max_tokens))


class FakeSearcher:
    def __init__(self, hits):
        self.hits = hits

    def search(self, method, question, k, filters):
        return self.hits[:k]


def test_sources_are_numbered_and_labelled():
    text = format_sources(HITS)
    assert text.startswith("[S1] (PNC 2025 10-K, item 7, chunk 17550)")
    assert "[S2] (PNC 2025 10-K, item 7, chunk 17549)" in text


def test_answer_sends_sources_and_question_to_the_llm():
    llm = FakeLLM("NII rose $0.9 billion on lower funding costs [S1].")
    ans = answer("Why did PNC's NII rise?", FakeSearcher(HITS), llm, k=2)
    system, user = llm.prompts[0]
    assert "ONLY the numbered sources" in system
    assert "[S1]" in user and "[S2]" in user and user.endswith("Question: Why did PNC's NII rise?")
    assert ans.text.endswith("[S1].")


def test_no_sources_means_no_llm_call():
    llm = FakeLLM()
    ans = answer("anything", FakeSearcher([]), llm)
    assert ans.sources == [] and llm.prompts == []


def test_citation_check_counts_cited_sentences_and_invalid_refs():
    text = "NII rose $0.9 billion [S1]. Funding costs fell [S2]. This was a strong year overall. See also [S7]."
    c = citation_check(text, n_sources=2)
    assert c["sentences"] == 4
    assert c["cited_sentences"] == 3
    assert c["invalid_citations"] == [7]
    assert c["sources_used"] == [1, 2]


def test_citation_check_handles_headings_line_breaks_and_leading_citations():
    # The shape Claude actually produced: a heading, paragraphs, citations at sentence starts.
    text = ("# Funding costs and NII\n\n"
            "Lower funding costs helped NII. [S1] NII increased $0.9 billion in 2025.\n\n"
            "Deposit betas were 41% [S3]. The sources don't quantify deposit pricing alone.")
    c = citation_check(text, n_sources=5)
    assert c["sentences"] == 4  # heading ignored; 2 + 2 sentences
    assert c["cited_sentences"] == 2


def test_parse_json_tolerates_fences_and_prose():
    assert parse_json('Here you go:\n```json\n{"score": 4, "reason": "ok"}\n```') == {"score": 4, "reason": "ok"}
    with pytest.raises(ValueError):
        parse_json("no json here")


def test_faithfulness_is_share_of_supported_claims():
    verdicts = ["supported", "supported", "unsupported", "contradicted"]
    claims = [{"verdict": v} for v in verdicts]
    assert faithfulness_score(claims) == 0.5
    assert faithfulness_score([]) is None


def test_judge_combines_faithfulness_and_relevance():
    llm = FakeLLM(
        json.dumps({"claims": [
            {"claim": "NII rose $0.9 billion", "verdict": "supported", "sources": ["S1"], "reason": ""},
            {"claim": "Deposit growth was 10%", "verdict": "unsupported", "sources": [], "reason": "not in sources"},
        ]}),
        json.dumps({"score": 4, "reason": "answers the question with a small gap"}),
    )
    ans = Answer("Why did NII rise?", "hybrid", Filters(), HITS, "NII rose $0.9 billion [S1]. Deposits grew 10% [S2].")
    v = judge(ans, llm)
    assert v.faithfulness == 0.5
    assert v.relevance_score == 4 and v.relevance == 0.75
