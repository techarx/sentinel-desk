"""Writes filings to Postgres (source of truth) and OpenSearch (BM25 index).

Postgres: one transaction per filing, as the least-privilege ingest_writer
role (connection settings from the standard PG* environment variables).

OpenSearch documents use the Postgres chunk id as their _id, so indexing is
idempotent; reconcile() repairs any filing whose chunks are missing there
(for example if a previous run died between the two writes).
"""

from __future__ import annotations

import logging
import os

import psycopg
from opensearchpy import OpenSearch, helpers

from .chunker import Chunk
from .edgar import Filing
from .embed import MODEL_NAME
from .items import Section

log = logging.getLogger(__name__)

INDEX = "chunks"
INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},  # single-node cluster
    "mappings": {
        "properties": {
            "chunk_id": {"type": "long"},
            "text": {"type": "text", "analyzer": "english"},
            "ticker": {"type": "keyword"},
            "fiscal_year": {"type": "integer"},
            "fiscal_period": {"type": "keyword"},
            "form": {"type": "keyword"},
            "item": {"type": "keyword"},
            "accession_no": {"type": "keyword"},
            "filed_at": {"type": "date"},
        }
    },
}


# -- Postgres ------------------------------------------------------------------


def connect() -> psycopg.Connection:
    # autocommit=True matters: without it psycopg wraps everything in one outer
    # transaction that is only saved by an explicit commit(), and the
    # `with conn.transaction()` blocks below become mere savepoints inside it.
    # With it, each per-filing block is a real transaction that commits on exit.
    # Settings (PGHOST, PGUSER, PGPASSWORD, ...) come from the environment.
    return psycopg.connect("", autocommit=True)


def loaded_accessions(conn: psycopg.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT accession_no FROM filings")}


def save_filing(
    conn: psycopg.Connection,
    filing: Filing,
    sections: dict[str, Section],
    chunks: dict[str, list[Chunk]],
    vectors: dict[str, list[list[float]]],
) -> None:
    with conn.transaction():
        filing_id = conn.execute(
            """INSERT INTO filings (cik, ticker, company_name, form, fiscal_year, fiscal_period,
                                    period_end, accession_no, filed_at, source_url)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (filing.cik, filing.ticker, filing.company_name, filing.form, filing.fiscal_year,
             filing.fiscal_period, filing.period_end, filing.accession_no, filing.filed_at, filing.url),
        ).fetchone()[0]

        for item, section in sections.items():
            section_id = conn.execute(
                "INSERT INTO sections (filing_id, item, title, char_count) VALUES (%s, %s, %s, %s) RETURNING id",
                (filing_id, item, section.title, len(section.text)),
            ).fetchone()[0]
            items_chunks = chunks[item]
            if not items_chunks:
                continue
            # One round trip per section: arrays unnested server-side.
            rows = conn.execute(
                """INSERT INTO chunks (section_id, ordinal, text, token_count, ticker, fiscal_year, form, item)
                   SELECT %s, u.ordinal, u.text, u.tokens, %s, %s, %s, %s
                     FROM unnest(%s::int[], %s::text[], %s::int[]) AS u(ordinal, text, tokens)
                   RETURNING id, ordinal""",
                (section_id, filing.ticker, filing.fiscal_year, filing.form, item,
                 list(range(len(items_chunks))), [c.text for c in items_chunks],
                 [c.token_count for c in items_chunks]),
            ).fetchall()
            ids_by_ordinal = {ordinal: chunk_id for chunk_id, ordinal in rows}
            conn.execute(
                """INSERT INTO chunk_embeddings (chunk_id, model, embedding)
                   SELECT u.chunk_id, %s, u.vec::vector
                     FROM unnest(%s::bigint[], %s::text[]) AS u(chunk_id, vec)""",
                (MODEL_NAME, [ids_by_ordinal[i] for i in range(len(items_chunks))],
                 ["[" + ",".join(f"{x:.7f}" for x in v) + "]" for v in vectors[item]]),
            )


# -- OpenSearch ----------------------------------------------------------------


def opensearch() -> OpenSearch:
    client = OpenSearch(
        hosts=[os.environ.get("OPENSEARCH_URL", "https://opensearch-cluster-master:9200")],
        http_auth=(os.environ.get("OPENSEARCH_USER", "admin"), os.environ["OPENSEARCH_PASSWORD"]),
        # Self-signed demo certificates inside the cluster; mTLS via Istio replaces this in Phase 5.
        verify_certs=False,
        ssl_show_warn=False,
        timeout=120,
    )
    if not client.indices.exists(index=INDEX):
        client.indices.create(index=INDEX, body=INDEX_BODY)
    return client


def _documents(conn: psycopg.Connection, accession_no: str):
    rows = conn.execute(
        """SELECT c.id, c.text, c.ticker, c.fiscal_year, f.fiscal_period, c.form, c.item, f.accession_no, f.filed_at
             FROM chunks c JOIN sections s ON s.id = c.section_id JOIN filings f ON f.id = s.filing_id
            WHERE f.accession_no = %s""",
        (accession_no,),
    )
    for chunk_id, text, ticker, year, period, form, item, acc, filed in rows:
        yield {
            "_index": INDEX,
            "_id": chunk_id,
            "_source": {
                "chunk_id": chunk_id, "text": text, "ticker": ticker, "fiscal_year": year,
                "fiscal_period": period, "form": form, "item": item, "accession_no": acc,
                "filed_at": filed.isoformat(),
            },
        }


def index_filing(conn: psycopg.Connection, client: OpenSearch, accession_no: str) -> int:
    indexed, _ = helpers.bulk(client, _documents(conn, accession_no), chunk_size=500, request_timeout=120)
    return indexed


def reconcile(conn: psycopg.Connection, client: OpenSearch) -> int:
    """Make OpenSearch match Postgres (the source of truth).

    - deletes documents whose filing is not in Postgres (e.g. a run that
      indexed but then failed to commit);
    - re-indexes any filing whose chunk count differs.
    """
    client.indices.refresh(index=INDEX)
    counts = conn.execute(
        """SELECT f.accession_no, count(c.id) FROM filings f
             LEFT JOIN sections s ON s.filing_id = f.id LEFT JOIN chunks c ON c.section_id = s.id
            GROUP BY f.accession_no"""
    ).fetchall()

    orphans = client.delete_by_query(
        index=INDEX,
        body={"query": {"bool": {"must_not": {"terms": {"accession_no": [a for a, _ in counts]}}}}},
        refresh=True,
        conflicts="proceed",
    )["deleted"]
    if orphans:
        log.warning("Deleted %s OpenSearch documents whose filing is not in Postgres", orphans)

    repaired = 0
    for accession_no, pg_count in counts:
        os_count = client.count(index=INDEX, body={"query": {"term": {"accession_no": accession_no}}})["count"]
        if os_count != pg_count:
            log.warning("Re-indexing %s: %s chunks in Postgres, %s in OpenSearch", accession_no, pg_count, os_count)
            index_filing(conn, client, accession_no)
            repaired += 1
    return repaired
