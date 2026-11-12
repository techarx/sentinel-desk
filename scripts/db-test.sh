#!/usr/bin/env bash
# Tests the database migrations against a throwaway Postgres + pgvector in Docker.
# Used both on the dev machine (make db-test) and in CI.
#
#  1. starts Postgres 17 with pgvector, creates the same roles CloudNativePG creates
#  2. builds the migrations image and runs: upgrade head -> downgrade base -> upgrade head
#  3. checks tables, indexes and that each role can do only what it should
#  4. optionally writes the Mermaid ER diagram (ER_OUT=docs/data-model.md)
#
# KEEP_DB=1 leaves the migrated Postgres running on the docker network
# "sentinel-dbtest" for a follow-on test (scripts/trades-test.sh uses this).
set -euo pipefail

NET=sentinel-dbtest
PG=sentinel-dbtest-pg
IMG=sentinel-db-migrate:test
PW=test-only-password

cleanup() { docker rm -f "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
cleanup
[[ "${KEEP_DB:-}" == 1 ]] || trap cleanup EXIT

echo "==> Starting throwaway Postgres 17 + pgvector"
docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_PASSWORD="$PW" pgvector/pgvector:pg17 >/dev/null
# During first-time init Postgres listens on a socket only; TCP answers once it is really ready.
for _ in $(seq 60); do docker exec "$PG" psql -h 127.0.0.1 -U postgres -tAc 'select 1' >/dev/null 2>&1 && break; sleep 1; done

psql_admin() { docker exec -i "$PG" psql -h 127.0.0.1 -U postgres -v ON_ERROR_STOP=1 -tA "$@"; }
psql_admin -c "CREATE ROLE sentinel LOGIN PASSWORD '$PW';" -c "CREATE DATABASE sentinel OWNER sentinel;" >/dev/null
# What CloudNativePG does in the cluster: pgvector extension + managed login roles.
psql_admin -d sentinel -c "CREATE EXTENSION vector;" \
   -c "CREATE ROLE ingest_writer LOGIN PASSWORD '$PW';" \
   -c "CREATE ROLE stream_writer LOGIN PASSWORD '$PW';" \
   -c "CREATE ROLE trade_generator LOGIN PASSWORD '$PW';" \
   -c "CREATE ROLE readonly_analyst LOGIN PASSWORD '$PW';" >/dev/null

echo "==> Building migrations image"
docker build -q -t "$IMG" services/db >/dev/null

migrate() {
  docker run --rm --network "$NET" \
    -e PGHOST="$PG" -e PGUSER=sentinel -e PGPASSWORD="$PW" -e PGDATABASE=sentinel -e PGSSLMODE=disable \
    "$IMG" "$@" 2>&1 | sed 's/^/    /'
}
echo "==> upgrade head";   migrate upgrade head
echo "==> downgrade base"; migrate downgrade base
echo "==> upgrade head";   migrate upgrade head

# --- checks ---------------------------------------------------------------
fails=0
check() {  # check "<description>" "<expected>" "<role>" "<sql>"
  local got
  got=$(docker exec -e PGPASSWORD="$PW" "$PG" psql -h 127.0.0.1 -U "$3" -d sentinel -tA -c "$4" 2>&1 | tail -1) || true
  if [[ "$got" == *"$2"* ]]; then echo "  PASS  $1"; else echo "  FAIL  $1 (expected '$2', got '$got')"; fails=$((fails+1)); fi
}

echo "==> Checks"
check "current revision is 0003"                     "0003" sentinel "select version_num from alembic_version"
check "11 tables created"                            "11"   sentinel "select count(*) from information_schema.tables where table_schema='public' and table_name <> 'alembic_version'"
check "HNSW vector index exists"                     "1"    sentinel "select count(*) from pg_indexes where indexname='chunk_embeddings_hnsw_idx'"
check "7 PII columns registered"                     "7"    sentinel "select count(*) from pii_columns"

check "ingest_writer can insert a filing"            "INSERT 0 1" ingest_writer \
  "insert into filings (cik,ticker,company_name,form,fiscal_year,fiscal_period,period_end,accession_no,filed_at,source_url) values ('1','TST','Test','10-K',2025,'FY','2025-12-31','test-1','2026-02-01','http://x')"
check "ingest_writer cannot read trades"             "permission denied" ingest_writer "select count(*) from trades"
check "stream_writer cannot write filings"           "permission denied" stream_writer "delete from filings"
check "stream_writer cannot update trades"           "permission denied" stream_writer "update trades set notional = 1"
check "trade_generator can read counterparties"      "0"    trade_generator "select count(*) from counterparties"
check "trade_generator cannot write trades"          "permission denied" trade_generator "delete from trades"
check "trade_generator cannot read customers"        "permission denied" trade_generator "select id from customers"
check "readonly_analyst can read filings"            "1"    readonly_analyst "select count(*) from filings"
check "readonly_analyst can read non-PII customer columns" "0" readonly_analyst "select count(*) from (select id, desk_id, segment, created_at from customers) c"
check "readonly_analyst cannot read customers.ssn"   "permission denied" readonly_analyst "select ssn from customers"
check "readonly_analyst cannot select * from customers" "permission denied" readonly_analyst "select * from customers"
check "readonly_analyst cannot write"                "permission denied" readonly_analyst "delete from filings"
check "vector search query runs"                     "0"    readonly_analyst \
  "select count(*) from (select chunk_id from chunk_embeddings order by embedding <=> array_fill(0.1, array[384])::vector limit 5) t"

# --- optional ER diagram ----------------------------------------------------
if [[ -n "${ER_OUT:-}" ]]; then
  echo "==> Writing ER diagram to ${ER_OUT}"
  {
    echo "# Data model"
    echo
    echo "Generated from the live schema by \`make er-diagram\` (scripts/db-test.sh). Do not edit by hand."
    echo "Columns marked \`PII\` are listed in the \`pii_columns\` table; \`readonly_analyst\` cannot read them."
    echo
    echo '```mermaid'
    psql_admin -d sentinel -f - < scripts/er-diagram.sql
    echo '```'
  } > "${ER_OUT}"
fi

if [[ $fails -gt 0 ]]; then echo "==> ${fails} check(s) FAILED"; exit 1; fi
echo "==> All checks passed"
