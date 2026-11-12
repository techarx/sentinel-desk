import itertools

from ingest_edgar.chunker import WhitespaceTokenizer, chunk_text

TOK = WhitespaceTokenizer()


def sentence(i: int, words: int = 20) -> str:
    return f"Sentence {i} " + " ".join(["word"] * (words - 3)) + " end."


def test_chunks_stay_within_limits():
    text = " ".join(sentence(i) for i in range(200))  # 4,000 words on one line
    chunks = chunk_text(text, TOK, target=450, max_tokens=510, overlap=50)
    assert len(chunks) > 1
    assert all(c.token_count <= 510 for c in chunks)
    assert all(c.token_count >= 100 for c in chunks)


def test_consecutive_chunks_overlap_by_whole_sentences():
    text = " ".join(sentence(i) for i in range(100))
    chunks = chunk_text(text, TOK, target=200, max_tokens=260, overlap=50)
    for first, second in itertools.pairwise(chunks):
        last_sentences = first.text.split("\n")[-2:]
        assert second.text.split("\n")[0] in last_sentences


def test_cuts_happen_at_sentence_ends():
    text = " ".join(sentence(i) for i in range(60))
    for chunk in chunk_text(text, TOK, target=200, max_tokens=260, overlap=50):
        assert chunk.text.endswith("end.")


def test_small_tail_is_merged_into_previous_chunk():
    # 9 sentences x 20 words: with target 160, the last chunk would be tiny.
    text = " ".join(sentence(i) for i in range(9))
    chunks = chunk_text(text, TOK, target=160, max_tokens=260, overlap=0, min_tail=50)
    assert len(chunks) == 1
    assert chunks[0].token_count == 180


def test_overlong_sentence_is_hard_split():
    text = " ".join(["x"] * 1200)  # one "sentence" far longer than a chunk
    chunks = chunk_text(text, TOK, target=450, max_tokens=510, overlap=50)
    assert all(c.token_count <= 510 for c in chunks)
    assert sum(c.token_count for c in chunks) >= 1200


def test_empty_text_gives_no_chunks():
    assert chunk_text("   \n\n ", TOK) == []
