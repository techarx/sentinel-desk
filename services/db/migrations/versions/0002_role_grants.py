"""Least-privilege grants for the service roles.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-11

The roles themselves (ingest_writer, stream_writer, readonly_analyst) are
created by CloudNativePG from deploy/data/postgres/cluster.yaml. This migration
decides what each one may touch:

| Role             | May do                                                        |
|------------------|---------------------------------------------------------------|
| ingest_writer    | write filings, sections, chunks, embeddings                   |
| stream_writer    | read reference data; insert trades; upsert exposures          |
| readonly_analyst | read everything except PII columns listed in pii_columns      |
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ROLES = ("ingest_writer", "stream_writer", "readonly_analyst")


def upgrade() -> None:
    op.execute("""
    -- ingest-edgar
    GRANT SELECT, INSERT, UPDATE ON filings, sections, chunks, chunk_embeddings TO ingest_writer;

    -- trade-consumer: trades are append-only (no UPDATE/DELETE); exposures are upserted
    GRANT SELECT ON desks, books, counterparties TO stream_writer;
    GRANT SELECT, INSERT ON trades TO stream_writer;
    GRANT SELECT, INSERT, UPDATE ON exposures TO stream_writer;

    -- trades_sql MCP tool: read-only, and never raw PII
    GRANT SELECT ON filings, sections, chunks, chunk_embeddings,
                    desks, books, counterparties, trades, exposures, pii_columns
          TO readonly_analyst;
    """)

    # Column-level grant on customers: every column NOT listed in pii_columns.
    # Driven by the registry, so a newly flagged column is excluded automatically
    # the next time grants are rebuilt.
    op.execute("""
    DO $$
    DECLARE cols text;
    BEGIN
      SELECT string_agg(quote_ident(c.column_name), ', ' ORDER BY c.ordinal_position)
        INTO cols
        FROM information_schema.columns c
       WHERE c.table_schema = 'public'
         AND c.table_name = 'customers'
         AND NOT EXISTS (SELECT 1 FROM pii_columns p
                          WHERE p.table_name = c.table_name AND p.column_name = c.column_name);
      EXECUTE format('GRANT SELECT (%s) ON customers TO readonly_analyst', cols);
    END $$;
    """)

    # Nobody but the owner can create objects in the schema.
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC;")


def downgrade() -> None:
    for role in ROLES:
        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role};")
    # Column-level grants are not removed by REVOKE ALL ON TABLE.
    op.execute("REVOKE SELECT ON customers FROM readonly_analyst;")
    op.execute("""
    DO $$
    DECLARE col record;
    BEGIN
      FOR col IN SELECT column_name FROM information_schema.columns
                  WHERE table_schema = 'public' AND table_name = 'customers' LOOP
        EXECUTE format('REVOKE SELECT (%I) ON customers FROM readonly_analyst', col.column_name);
      END LOOP;
    END $$;
    """)
