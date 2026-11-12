"""bge-small-en-v1.5 embeddings via fastembed (ONNX Runtime, no PyTorch).

The model and its tokenizer are baked into the image at build time
(download_model.py), so the Job never downloads anything at run time.

Note for Phase 2: bge models expect search QUERIES to be prefixed with
"Represent this sentence for searching relevant passages: "; passages (what we
embed here) take no prefix.
"""

from __future__ import annotations

import os
from pathlib import Path

from tokenizers import Tokenizer as HFTokenizerImpl

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/models"))


class HFTokenizer:
    """The model's own WordPiece tokenizer, so token counts match what the model sees."""

    def __init__(self, path: Path = MODEL_DIR / "tokenizer.json"):
        self._tok = HFTokenizerImpl.from_file(str(path))
        self._tok.no_truncation()
        self._tok.no_padding()

    def count(self, text: str) -> int:
        return len(self._tok.encode(text, add_special_tokens=False).ids)

    def split(self, text: str, max_tokens: int) -> list[str]:
        """Cut at token boundaries, slicing the ORIGINAL text (decoding would lower-case it)."""
        offsets = self._tok.encode(text, add_special_tokens=False).offsets
        pieces = []
        for i in range(0, len(offsets), max_tokens):
            window = offsets[i : i + max_tokens]
            pieces.append(text[window[0][0] : window[-1][1]])
        return pieces


class Embedder:
    def __init__(self, cache_dir: Path = MODEL_DIR):
        from fastembed import TextEmbedding  # heavy import, only when embedding

        self._model = TextEmbedding(MODEL_NAME, cache_dir=str(cache_dir))

    def embed(self, texts: list[str], batch_size: int = 64) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts, batch_size=batch_size)]
