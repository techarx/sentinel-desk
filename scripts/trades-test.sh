#!/usr/bin/env bash
# Integration test for the trade stream against real Postgres, Redis and Neo4j
# containers (same images as the cluster). Used on the dev machine (make
# trades-test) and in CI.
#
#  1. migrated Postgres with the service roles (scripts/db-test.sh, KEEP_DB=1)
#  2. seed reference data, twice (the second run must change nothing)
#  3. generate trades for a few seconds as trade_generator, consume as stream_writer
#  4. REDELIVER: publish the first trades again with the same trade IDs and
#     consume; nothing may be counted twice
#  5. check Postgres totals, Neo4j totals and the stream's pending list agree
#
# GLEIF=1 also loads real bank subsidiaries from the GLEIF API (needs internet).
set -euo pipefail

NET=sentinel-dbtest
PG=sentinel-dbtest-pg
REDIS=sentinel-test-redis
NEO=sentinel-test-neo4j
IMG=sentinel-trades:test
PW=test-only-password
RATE=${RATE:-200}
DURATION=${DURATION:-10}

cleanup() {
  docker rm -f "$REDIS" "$NEO" "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

KEEP_DB=1 ./scripts/db-test.sh

echo "==> Starting Redis and Neo4j"
docker run -d --name "$REDIS" --network "$NET" redis:7.4-alpine \
  redis-server --requirepass "$PW" --appendonly yes >/dev/null
docker run -d --name "$NEO" --network "$NET" -e NEO4J_AUTH="neo4j/$PW" neo4j:2026.10.2-community >/dev/null
for _ in $(seq 90); do
  docker exec "$NEO" cypher-shell -u neo4j -p "$PW" "RETURN 1" >/dev/null 2>&1 && break
  sleep 2
done

echo "==> Building trades image"
docker build -q -t "$IMG" -f services/trades/Dockerfile . >/dev/null

run_as() {  # run_as <postgres role> <trades args...>
  local role=$1; shift
  docker run --rm --network "$NET" \
    -e PGHOST="$PG" -e PGUSER="$role" -e PGPASSWORD="$PW" -e PGDATABASE=sentinel -e PGSSLMODE=disable \
    -e REDIS_HOST="$REDIS" -e REDIS_PASSWORD="$PW" \
    -e NEO4J_URI="bolt://$NEO:7687" -e NEO4J_AUTH="neo4j/$PW" \
    "$IMG" "$@" 2>&1 | sed 's/^/    /'
}
pg() { docker exec -e PGPASSWORD="$PW" "$PG" psql -h 127.0.0.1 -U postgres -d sentinel -tA -c "$1"; }
cypher() { docker exec "$NEO" cypher-shell -u neo4j -p "$PW" --format plain "$1" | tail -1; }
rcli() { docker exec "$REDIS" redis-cli -a "$PW" --no-auth-warning "$@"; }

seed_args=(--no-gleif)
[[ "${GLEIF:-0}" == 1 ]] && seed_args=()
echo "==> seed (schema owner)";            run_as sentinel seed "${seed_args[@]}"
counts_1=$(pg "select (select count(*) from desks),(select count(*) from books),(select count(*) from counterparties),(select count(*) from customers)")
echo "==> seed again (must change nothing)"; run_as sentinel seed "${seed_args[@]}"
counts_2=$(pg "select (select count(*) from desks),(select count(*) from books),(select count(*) from counterparties),(select count(*) from customers)")

echo "==> generate ${RATE}/s for ${DURATION}s (trade_generator)"
run_as trade_generator generate --rate "$RATE" --duration "$DURATION" --no-bursts --seed 1
first=$(rcli XLEN trades)
echo "==> consume (stream_writer)"
run_as stream_writer consume --exit-when-idle 5

echo "==> redeliver: same random seed => the same first trade IDs, published again"
run_as trade_generator generate --rate "$RATE" --duration 2 --no-bursts --seed 1
replayed=$(( $(rcli XLEN trades) - first ))
run_as stream_writer consume --exit-when-idle 5

# --- checks ---------------------------------------------------------------
fails=0
check() {  # check "<description>" "<expected>" "<actual>"
  if [[ "$3" == "$2" ]]; then echo "  PASS  $1"; else echo "  FAIL  $1 (expected '$2', got '$3')"; fails=$((fails+1)); fi
}
echo "==> Checks ($first trades published, then $replayed re-published)"
check "seed: 8 desks, 24 books"                    "8|24" "$(cut -d'|' -f1,2 <<<"$counts_1")"
check "seed: 500 customers"                        "500"  "$(cut -d'|' -f4 <<<"$counts_1")"
check "seed is idempotent (second run adds nothing)" "$counts_1" "$counts_2"
check "every published trade stored exactly once"  "$first" "$(pg 'select count(*) from trades')"
check "re-published trades were all duplicates"     "t" "$(pg "select $replayed > 0")"
check "exposure gross = sum of trade notionals"     "t" "$(pg 'select (select sum(gross) from exposures) = (select sum(notional) from trades)')"
check "exposure net = buys - sells"                 "t" "$(pg "select (select sum(net) from exposures) = (select sum(case side when 'BUY' then notional else -notional end) from trades)")"
check "exposure trade_count = number of trades"     "t" "$(pg 'select (select sum(trade_count) from exposures) = (select count(*) from trades)')"
check "one Neo4j edge per exposures row"            "$(pg 'select count(*) from exposures')" "$(cypher 'MATCH ()-[t:TRADES_WITH]->() RETURN count(t)')"
check "Neo4j edge totals match Postgres"            "$(pg 'select round(sum(gross)) from exposures')" "$(cypher 'MATCH ()-[t:TRADES_WITH]->() RETURN toInteger(round(sum(t.gross)))')"
check "nothing left unacknowledged in the stream"   "0" "$(rcli XPENDING trades exposure | head -1)"
check "stream_writer cannot read customers"         "permission denied" "$(docker exec -e PGPASSWORD="$PW" "$PG" psql -h 127.0.0.1 -U stream_writer -d sentinel -tAc 'select id from customers' 2>&1 | grep -o 'permission denied' | head -1)"
if [[ "${GLEIF:-0}" == 1 ]]; then
  check "real subsidiaries linked to their bank"    "t" "$(pg "select count(*) > 0 from counterparties where not is_fictional")"
  check "every real counterparty's parent is allowlisted" "0" \
    "$(pg "select count(*) from counterparties where not is_fictional and parent_ticker not in ('BAC','C','WFC','GS','MS','USB','PNC','TFC','COF','BNY')")"
fi

if [[ $fails -gt 0 ]]; then echo "==> ${fails} check(s) FAILED"; exit 1; fi
echo "==> All checks passed"
