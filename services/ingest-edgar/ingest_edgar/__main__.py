"""Entry point: python -m ingest_edgar [--tickers BAC WFC] [--dry-run]"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from .chunker import chunk_text
from .config import banks, check_allowed
from .edgar import EdgarClient
from .html_text import html_to_text
from .items import ITEMS, split_filing

log = logging.getLogger("ingest_edgar")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest SEC filings for the allowlisted banks.")
    p.add_argument("--tickers", nargs="*", help="Subset of allowlisted tickers (default: all)")
    p.add_argument("--tenk", type=int, default=int(os.environ.get("N_10K", "3")), help="10-Ks per bank")
    p.add_argument("--tenq", type=int, default=int(os.environ.get("N_10Q", "3")), help="10-Qs per bank")
    p.add_argument("--cache-dir", type=Path, default=Path(os.environ.get("CACHE_DIR", "/cache")))
    p.add_argument("--dry-run", action="store_true", help="Download, split and chunk only; write nothing")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("opensearch").setLevel(logging.WARNING)
    args = parse_args(argv)

    allowlist = banks()
    tickers = check_allowed(args.tickers or list(allowlist), list(allowlist))
    edgar = EdgarClient(os.environ["SEC_USER_AGENT"], args.cache_dir)

    # Imported lazily so --dry-run works without the model or the databases.
    from .embed import Embedder, HFTokenizer

    tokenizer = HFTokenizer()
    report: list[tuple] = []
    errors = 0
    conn = os_client = embedder = None
    loaded: set[str] = set()
    if not args.dry_run:
        from . import store

        conn = store.connect()
        os_client = store.opensearch()
        embedder = Embedder()
        loaded = store.loaded_accessions(conn)

    for ticker in tickers:
        try:
            filings = edgar.recent_filings(ticker, allowlist[ticker][0], args.tenk, args.tenq)
        except Exception:
            errors += 1
            log.exception("%s: could not list filings", ticker)
            report.append((f"{ticker} (listing)", "ERROR", "", 0))
            continue
        for filing in filings:
            label = f"{ticker} {filing.form} {filing.fiscal_year} {filing.fiscal_period}"
            if filing.accession_no in loaded:
                report.append((label, "already loaded", "", 0))
                continue
            try:
                started = time.monotonic()
                text = html_to_text(edgar.document(filing))
                exhibit_text = None
                sections = split_filing(text, filing.form)
                if len(sections) < len(ITEMS):
                    exhibit = edgar.exhibit(filing, "EX-13")
                    if exhibit:
                        exhibit_text = html_to_text(exhibit)
                        sections = split_filing(text, filing.form, exhibit_text)
                chunks = {item: chunk_text(s.text, tokenizer) for item, s in sections.items()}
                n_chunks = sum(len(c) for c in chunks.values())
                found = " ".join(f"{item}({s.method[0]})" for item, s in sections.items())
                missing = " ".join(i for i in ITEMS if i not in sections)

                if not args.dry_run and n_chunks:
                    vectors = {item: embedder.embed([c.text for c in cs]) for item, cs in chunks.items()}
                    store.save_filing(conn, filing, sections, chunks, vectors)
                    store.index_filing(conn, os_client, filing.accession_no)
                report.append((label, found, f"missing: {missing}" if missing else "", n_chunks))
                log.info("%s: %s chunks, sections %s%s (%.1fs)", label, n_chunks, found,
                         f", missing {missing}" if missing else "", time.monotonic() - started)
            except Exception:
                errors += 1
                log.exception("%s (%s) failed", label, filing.accession_no)
                report.append((label, "ERROR", "", 0))

    if not args.dry_run:
        repaired = store.reconcile(conn, os_client)
        if repaired:
            log.info("Re-indexed %s filings in OpenSearch", repaired)

    print("\nfiling                     sections (i=item heading, t=title, e=EX-13)   chunks")
    for label, found, missing, n in report:
        print(f"{label:<26} {found:<22} {missing:<22} {n:>6}")
    total = sum(r[3] for r in report)
    print(f"\n{len(report)} filings, {total} new chunks, {errors} errors{' (dry run)' if args.dry_run else ''}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
