"""Cut a section into overlapping chunks that fit the embedding model.

Rules (see docs, Phase 1 plan):
- Target ~450 tokens, never more than 510 (bge-small-en-v1.5 reads 512 including
  its two special tokens, so anything longer would be silently cut off).
- ~50 tokens of overlap: the last whole sentences of a chunk repeat at the start
  of the next, so nothing that falls on a cut loses its context.
- Cuts land on line or sentence ends; only a single sentence longer than a chunk
  (usually a huge table row) is split mid-way.
- A leftover tail under 100 tokens is merged into the previous chunk if it fits.
- Chunks never cross sections: this module is called once per section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

TARGET_TOKENS = 450
MAX_TOKENS = 510
OVERLAP_TOKENS = 50
MIN_TAIL_TOKENS = 100

_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+(?=[\"'“(\[]?[A-Z0-9$])")


class Tokenizer(Protocol):
    def count(self, text: str) -> int: ...

    def split(self, text: str, max_tokens: int) -> list[str]: ...


@dataclass
class Chunk:
    text: str
    token_count: int


@dataclass
class _Unit:
    text: str
    tokens: int


def _units(text: str, tok: Tokenizer, max_unit: int) -> list[_Unit]:
    """Lines, then sentences, then hard token windows: each at most max_unit tokens."""
    units: list[_Unit] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        n = tok.count(line)
        if n <= max_unit:
            units.append(_Unit(line, n))
            continue
        for sentence in _SENTENCE_END.split(line):
            n = tok.count(sentence)
            if n <= max_unit:
                units.append(_Unit(sentence, n))
            else:
                units += [_Unit(piece, tok.count(piece)) for piece in tok.split(sentence, max_unit)]
    return [u for u in units if u.tokens > 0]


def chunk_text(
    text: str,
    tok: Tokenizer,
    target: int = TARGET_TOKENS,
    max_tokens: int = MAX_TOKENS,
    overlap: int = OVERLAP_TOKENS,
    min_tail: int = MIN_TAIL_TOKENS,
) -> list[Chunk]:
    units = _units(text, tok, max_unit=target - overlap)
    if not units:
        return []

    groups: list[list[int]] = []  # each chunk as a list of unit indexes
    current: list[int] = []
    current_tokens = 0
    fresh = 0  # units added since the last cut (overlap units don't count)

    for i, unit in enumerate(units):
        if fresh and current_tokens + unit.tokens > target:
            groups.append(current)
            tail: list[int] = []
            tail_tokens = 0
            for j in reversed(current):
                if tail_tokens + units[j].tokens > overlap:
                    break
                tail.insert(0, j)
                tail_tokens += units[j].tokens
            current, current_tokens, fresh = tail, tail_tokens, 0
        current.append(i)
        current_tokens += unit.tokens
        fresh += 1
    if fresh:
        groups.append(current)

    # Merge a small tail into the previous chunk when the result still fits.
    if len(groups) > 1:
        last_tokens = sum(units[i].tokens for i in groups[-1])
        merged = sorted(set(groups[-2]) | set(groups[-1]))
        if last_tokens < min_tail and sum(units[i].tokens for i in merged) <= max_tokens:
            groups[-2:] = [merged]

    chunks = []
    for group in groups:
        body = "\n".join(units[i].text for i in group)
        chunks.append(Chunk(body, tok.count(body)))
    return chunks


class WhitespaceTokenizer:
    """Counts words. For tests, where the real tokenizer is not available."""

    def count(self, text: str) -> int:
        return len(text.split())

    def split(self, text: str, max_tokens: int) -> list[str]:
        words = text.split()
        return [" ".join(words[i : i + max_tokens]) for i in range(0, len(words), max_tokens)]
