"""Build step: download bge-small-en-v1.5 into the image and expose its tokenizer.

Usage: python download_model.py /models
"""

import shutil
import sys
from pathlib import Path

from fastembed import TextEmbedding

target = Path(sys.argv[1])
model = TextEmbedding("BAAI/bge-small-en-v1.5", cache_dir=str(target))
vector = next(iter(model.embed(["warm-up"])))
assert len(vector) == 384, f"unexpected embedding size {len(vector)}"

tokenizers = sorted(target.rglob("tokenizer.json"))
if not tokenizers:
    sys.exit("tokenizer.json not found in the downloaded model")
shutil.copy(tokenizers[0], target / "tokenizer.json")
print(f"model ready in {target}, tokenizer from {tokenizers[0]}")
