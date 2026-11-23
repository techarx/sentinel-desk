"""python -m retrieval {search|serve}

search: print vector, BM25 and hybrid results side by side (for learning and debugging).
serve:  HTTP API on :8000 (GET /search, GET /healthz), used by agents later.
"""

from __future__ import annotations

import argparse
import logging
import sys
import textwrap

from .models import Filters, Hit
from .search import Searcher

METHODS = ("vector", "bm25", "hybrid")


def _print_hits(method: str, hits: list[Hit], preview: int) -> None:
    title = {"vector": "VECTOR (meaning, pgvector)", "bm25": "KEYWORD (BM25, OpenSearch)",
             "hybrid": "HYBRID (RRF of both)"}[method]
    print(f"\n── {title} " + "─" * max(0, 76 - len(title)))
    if not hits:
        print("  (no results)")
    for rank, h in enumerate(hits, start=1):
        extra = ""
        if h.ranks:
            v, b = h.ranks.get("vector"), h.ranks.get("bm25")
            extra = f"  [vector #{v or '-'}, bm25 #{b or '-'}]"
        print(f"{rank:>2}. score {h.score:7.4f}  chunk {h.chunk_id:<6} {h.label()}{extra}")
        snippet = " ".join(h.text.split())[:preview]
        print(textwrap.indent(textwrap.fill(snippet, 100), "      "))


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.WARNING)
    p = argparse.ArgumentParser(prog="retrieval")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="Search and print results")
    s.add_argument("question")
    s.add_argument("-k", type=int, default=5, help="results per method (default 5)")
    s.add_argument("--method", choices=(*METHODS, "all"), default="all")
    s.add_argument("--ticker", default="", help="e.g. BAC or BAC,WFC")
    s.add_argument("--year", default="", help="e.g. 2025")
    s.add_argument("--form", default="", help="10-K or 10-Q")
    s.add_argument("--item", default="", help="1A, 7, 7A or 8")
    s.add_argument("--no-instruction", action="store_true",
                   help="embed the question WITHOUT the bge query instruction (to compare)")
    s.add_argument("--preview", type=int, default=220, help="characters of text to show per hit")

    sub.add_parser("serve", help="Run the HTTP API on :8000")
    args = p.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        from .api import app

        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")  # listens on all interfaces inside the pod
        return 0

    filters = Filters.parse(args.ticker, args.year, args.form, args.item)
    searcher = Searcher(use_query_instruction=not args.no_instruction)
    print(f'Question: "{args.question}"')
    print(f"Filters: {filters.describe()}   k={args.k}"
          f"{'   (no query instruction)' if args.no_instruction else ''}")
    for method in METHODS if args.method == "all" else (args.method,):
        _print_hits(method, searcher.search(method, args.question, args.k, filters), args.preview)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
