# Data model

Generated from the live schema by `make er-diagram` (scripts/db-test.sh). Do not edit by hand.
Columns marked `PII` are listed in the `pii_columns` table; `readonly_analyst` cannot read them.

```mermaid
erDiagram
  books {
    integer id PK
    smallint desk_id FK
    text name
  }
  chunk_embeddings {
    bigint chunk_id PK,FK
    text model
    vector embedding
    timestamptz created_at
  }
  chunks {
    bigint id PK
    bigint section_id FK
    integer ordinal
    text text
    integer token_count
    text ticker
    integer fiscal_year
    text form
    text item
  }
  counterparties {
    bigint id PK
    char lei
    text name
    text kind
    char parent_lei
    text parent_ticker
    char country
    boolean is_fictional
  }
  customers {
    bigint id PK
    smallint desk_id FK
    text segment
    text full_name "PII: name"
    text email "PII: contact"
    text phone "PII: contact"
    text ssn "PII: government_id"
    date date_of_birth "PII: date_of_birth"
    text address "PII: address"
    text account_number "PII: financial_account"
    timestamptz created_at
  }
  desks {
    smallint id PK
    text name
    text region
  }
  exposures {
    smallint desk_id PK,FK
    bigint counterparty_id PK,FK
    numeric gross
    numeric net
    bigint trade_count
    timestamptz last_trade_at
    timestamptz updated_at
  }
  filings {
    bigint id PK
    text cik
    text ticker
    text company_name
    text form
    integer fiscal_year
    text fiscal_period
    date period_end
    text accession_no
    date filed_at
    text source_url
    timestamptz ingested_at
  }
  pii_columns {
    text table_name PK
    text column_name PK
    text category
  }
  sections {
    bigint id PK
    bigint filing_id FK
    text item
    text title
    integer char_count
  }
  trades {
    uuid trade_id PK
    timestamptz ts
    smallint desk_id FK
    integer book_id FK
    bigint counterparty_id FK
    text asset_class
    text instrument
    text side
    numeric notional
    char ccy
    text trader
    timestamptz ingested_at
  }
  books ||--o{ trades : "book_id"
  chunks ||--o{ chunk_embeddings : "chunk_id"
  counterparties ||--o{ exposures : "counterparty_id"
  counterparties ||--o{ trades : "counterparty_id"
  desks ||--o{ books : "desk_id"
  desks ||--o{ customers : "desk_id"
  desks ||--o{ exposures : "desk_id"
  desks ||--o{ trades : "desk_id"
  filings ||--o{ sections : "filing_id"
  sections ||--o{ chunks : "section_id"
```
