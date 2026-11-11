"""Initial schema: filings, chunks + embeddings, reference data, trades, exposures, customers.

Revision ID: 0001
Revises:
Create Date: 2026-11-11

Written as plain SQL so the schema reads the same here as in psql.
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector is created by CloudNativePG at cluster setup (needs superuser);
    # this is a no-op there and documents the dependency.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # ------------------------------------------------------------------
    # SEC filings -> sections (10-K Items) -> chunks -> embeddings
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE filings (
        id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        cik           text        NOT NULL,
        ticker        text        NOT NULL,
        company_name  text        NOT NULL,
        form          text        NOT NULL CHECK (form IN ('10-K', '10-Q')),
        fiscal_year   int         NOT NULL,
        fiscal_period text        NOT NULL CHECK (fiscal_period IN ('FY', 'Q1', 'Q2', 'Q3')),
        period_end    date        NOT NULL,
        accession_no  text        NOT NULL UNIQUE,   -- SEC's ID for the filing; makes ingestion re-runnable
        filed_at      date        NOT NULL,
        source_url    text        NOT NULL,
        ingested_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX filings_ticker_year_idx ON filings (ticker, fiscal_year);

    CREATE TABLE sections (
        id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        filing_id  bigint NOT NULL REFERENCES filings (id) ON DELETE CASCADE,
        item       text   NOT NULL,                 -- '1A', '7', '7A', '8'
        title      text   NOT NULL,
        char_count int    NOT NULL,
        UNIQUE (filing_id, item)
    );

    -- ticker / fiscal_year / form / item are copied from the parent rows so
    -- Phase 2 metadata filters work without joins.
    CREATE TABLE chunks (
        id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        section_id  bigint NOT NULL REFERENCES sections (id) ON DELETE CASCADE,
        ordinal     int    NOT NULL,                -- position within the section
        text        text   NOT NULL,
        token_count int    NOT NULL CHECK (token_count > 0),
        ticker      text   NOT NULL,
        fiscal_year int    NOT NULL,
        form        text   NOT NULL,
        item        text   NOT NULL,
        UNIQUE (section_id, ordinal)
    );
    CREATE INDEX chunks_filter_idx ON chunks (ticker, fiscal_year, item);

    -- 384 dimensions = bge-small-en-v1.5. A new model gets a new table or column.
    CREATE TABLE chunk_embeddings (
        chunk_id   bigint      PRIMARY KEY REFERENCES chunks (id) ON DELETE CASCADE,
        model      text        NOT NULL,
        embedding  vector(384) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    );
    -- HNSW: approximate nearest-neighbour index for fast cosine-similarity search.
    CREATE INDEX chunk_embeddings_hnsw_idx ON chunk_embeddings USING hnsw (embedding vector_cosine_ops);
    """)

    # ------------------------------------------------------------------
    # Reference data: desks, books, counterparties
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE desks (
        id     smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        name   text NOT NULL UNIQUE,                -- e.g. 'Rates NY'
        region text NOT NULL CHECK (region IN ('AMER', 'EMEA', 'APAC'))
    );

    CREATE TABLE books (
        id      int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        desk_id smallint NOT NULL REFERENCES desks (id),
        name    text NOT NULL UNIQUE
    );

    -- Allowlist only (config/entities.yaml): subsidiaries of the listed banks,
    -- or fictional entities. is_fictional makes the distinction queryable.
    CREATE TABLE counterparties (
        id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        lei           char(20) UNIQUE,              -- NULL for fictional counterparties
        name          text     NOT NULL,
        kind          text     NOT NULL CHECK (kind IN ('bank_subsidiary', 'hedge_fund', 'asset_manager',
                                                        'corporate', 'insurer', 'pension_fund')),
        parent_lei    char(20),
        parent_ticker text,                         -- which allowlisted bank it belongs to, if any
        country       char(2)  NOT NULL,
        is_fictional  boolean  NOT NULL,
        CHECK (is_fictional OR lei IS NOT NULL)
    );
    CREATE INDEX counterparties_parent_ticker_idx ON counterparties (parent_ticker);
    """)

    # ------------------------------------------------------------------
    # Trades (append-only) and exposures (running totals, upserted)
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE trades (
        trade_id        uuid          PRIMARY KEY,  -- from the generator; makes processing idempotent
        ts              timestamptz   NOT NULL,     -- event time
        desk_id         smallint      NOT NULL REFERENCES desks (id),
        book_id         int           NOT NULL REFERENCES books (id),
        counterparty_id bigint        NOT NULL REFERENCES counterparties (id),
        asset_class     text          NOT NULL CHECK (asset_class IN ('rates', 'fx', 'credit', 'equity')),
        instrument      text          NOT NULL,
        side            text          NOT NULL CHECK (side IN ('BUY', 'SELL')),
        notional        numeric(20,2) NOT NULL CHECK (notional > 0),
        ccy             char(3)       NOT NULL,
        trader          text          NOT NULL,
        ingested_at     timestamptz   NOT NULL DEFAULT now()  -- processing time; ingested_at - ts = lag
    );
    CREATE INDEX trades_ts_idx ON trades (ts);
    CREATE INDEX trades_counterparty_idx ON trades (counterparty_id, ts);

    -- One row per desk + counterparty pair (see the upsert in trade-consumer).
    CREATE TABLE exposures (
        desk_id         smallint      NOT NULL REFERENCES desks (id),
        counterparty_id bigint        NOT NULL REFERENCES counterparties (id),
        gross           numeric(24,2) NOT NULL DEFAULT 0,   -- sum of notionals
        net             numeric(24,2) NOT NULL DEFAULT 0,   -- buys minus sells
        trade_count     bigint        NOT NULL DEFAULT 0,
        last_trade_at   timestamptz,
        updated_at      timestamptz   NOT NULL DEFAULT now(),
        PRIMARY KEY (desk_id, counterparty_id)
    );
    """)

    # ------------------------------------------------------------------
    # Customers (fake PII) and the PII registry
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE customers (
        id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        desk_id        smallint    NOT NULL REFERENCES desks (id),
        segment        text        NOT NULL CHECK (segment IN ('retail', 'private_bank', 'institutional')),
        full_name      text        NOT NULL,
        email          text        NOT NULL,
        phone          text        NOT NULL,
        ssn            text        NOT NULL,
        date_of_birth  date        NOT NULL,
        address        text        NOT NULL,
        account_number text        NOT NULL UNIQUE,
        created_at     timestamptz NOT NULL DEFAULT now()
    );

    -- Machine-readable list of PII columns. Grants (0002), the guardrail
    -- sidecar (Phase 6) and OpenFGA rules (Phase 5) are driven from this.
    CREATE TABLE pii_columns (
        table_name  text NOT NULL,
        column_name text NOT NULL,
        category    text NOT NULL CHECK (category IN ('name', 'contact', 'government_id',
                                                      'date_of_birth', 'address', 'financial_account')),
        PRIMARY KEY (table_name, column_name)
    );
    INSERT INTO pii_columns (table_name, column_name, category) VALUES
        ('customers', 'full_name',      'name'),
        ('customers', 'email',          'contact'),
        ('customers', 'phone',          'contact'),
        ('customers', 'ssn',            'government_id'),
        ('customers', 'date_of_birth',  'date_of_birth'),
        ('customers', 'address',        'address'),
        ('customers', 'account_number', 'financial_account');

    -- Human-readable flags that show up in psql (\\d+ customers) and DB tools.
    COMMENT ON COLUMN customers.full_name      IS 'PII: name';
    COMMENT ON COLUMN customers.email          IS 'PII: contact';
    COMMENT ON COLUMN customers.phone          IS 'PII: contact';
    COMMENT ON COLUMN customers.ssn            IS 'PII: government_id (synthetic)';
    COMMENT ON COLUMN customers.date_of_birth  IS 'PII: date_of_birth';
    COMMENT ON COLUMN customers.address        IS 'PII: address';
    COMMENT ON COLUMN customers.account_number IS 'PII: financial_account';
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS pii_columns, customers, exposures, trades,
                         counterparties, books, desks,
                         chunk_embeddings, chunks, sections, filings;
    """)
