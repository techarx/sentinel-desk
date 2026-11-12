"""Load reference data: desks, books, counterparties, customers -> Postgres; banks,
counterparties, desks and SUBSIDIARY_OF links -> Neo4j.

Safe to re-run: every insert skips rows that already exist.
"""

from __future__ import annotations

import logging
import random

from faker import Faker

from . import connections, refdata

log = logging.getLogger(__name__)

N_CUSTOMERS = 500


def seed_postgres(conn, counterparties: list[refdata.Counterparty]) -> None:
    with conn.transaction():
        for name, region, _asset_class in refdata.DESKS:
            conn.execute(
                "INSERT INTO desks (name, region) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING", (name, region)
            )
        desk_ids = dict(conn.execute("SELECT name, id FROM desks").fetchall())
        for name, _region, _asset_class in refdata.DESKS:
            for letter in refdata.BOOKS_PER_DESK:
                conn.execute(
                    "INSERT INTO books (desk_id, name) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                    (desk_ids[name], f"{name} {letter}"),
                )

        # Real counterparties are unique by LEI; fictional ones have no LEI, so they are
        # inserted only once (when none exist yet).
        real = [c for c in counterparties if not c.is_fictional]
        fictional = [c for c in counterparties if c.is_fictional]
        for cp in real:
            conn.execute(
                """INSERT INTO counterparties (lei, name, kind, parent_lei, parent_ticker, country, is_fictional)
                   VALUES (%s, %s, %s, %s, %s, %s, false) ON CONFLICT (lei) DO NOTHING""",
                (cp.lei, cp.name, cp.kind, cp.parent_lei, cp.parent_ticker, cp.country),
            )
        if not conn.execute("SELECT 1 FROM counterparties WHERE is_fictional LIMIT 1").fetchone():
            for cp in fictional:
                conn.execute(
                    "INSERT INTO counterparties (name, kind, country, is_fictional) VALUES (%s, %s, %s, true)",
                    (cp.name, cp.kind, cp.country),
                )

        if not conn.execute("SELECT 1 FROM customers LIMIT 1").fetchone():
            fake = Faker("en_US")
            Faker.seed(42)
            rng = random.Random(42)
            segments = ["retail"] * 6 + ["private_bank"] * 3 + ["institutional"]
            ids = list(desk_ids.values())
            for i in range(N_CUSTOMERS):
                conn.execute(
                    """INSERT INTO customers (desk_id, segment, full_name, email, phone, ssn, date_of_birth,
                                              address, account_number)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (rng.choice(ids), rng.choice(segments), fake.name(), fake.email(), fake.phone_number(),
                     fake.ssn(), fake.date_of_birth(minimum_age=21, maximum_age=85),
                     fake.address().replace("\n", ", "), f"{9_000_000_000 + i:010d}"),
                )

    counts = conn.execute(
        """SELECT (SELECT count(*) FROM desks), (SELECT count(*) FROM books),
                  (SELECT count(*) FROM counterparties WHERE NOT is_fictional),
                  (SELECT count(*) FROM counterparties WHERE is_fictional), (SELECT count(*) FROM customers)"""
    ).fetchone()
    log.info("Postgres: %s desks, %s books, %s real + %s fictional counterparties, %s customers", *counts)


def seed_neo4j(conn, driver, entities: dict) -> None:
    desks = [
        {"id": i, "name": n, "region": r, "asset_class": dict((d[0], d[2]) for d in refdata.DESKS)[n]}
        for i, n, r in conn.execute("SELECT id, name, region FROM desks").fetchall()
    ]
    cps = [
        {"id": i, "name": n, "lei": lei, "kind": k, "country": c, "is_fictional": f, "parent_ticker": p}
        for i, n, lei, k, c, f, p in conn.execute(
            "SELECT id, name, lei, kind, country, is_fictional, parent_ticker FROM counterparties"
        ).fetchall()
    ]
    banks = [{"ticker": b.ticker, "lei": b.lei, "name": b.name} for b in refdata.banks(entities)]
    with driver.session() as s:
        for statement in (
            "CREATE CONSTRAINT desk_id IF NOT EXISTS FOR (d:Desk) REQUIRE d.id IS UNIQUE",
            "CREATE CONSTRAINT counterparty_id IF NOT EXISTS FOR (c:Counterparty) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT bank_ticker IF NOT EXISTS FOR (b:Bank) REQUIRE b.ticker IS UNIQUE",
        ):
            s.run(statement)
        s.run("UNWIND $rows AS r MERGE (d:Desk {id: r.id}) SET d += r", rows=desks)
        s.run("UNWIND $rows AS r MERGE (b:Bank {ticker: r.ticker}) SET b += r", rows=banks)
        s.run(
            """UNWIND $rows AS r
               MERGE (c:Counterparty {id: r.id}) SET c += r
               WITH c, r WHERE r.parent_ticker IS NOT NULL
               MATCH (b:Bank {ticker: r.parent_ticker})
               MERGE (c)-[:SUBSIDIARY_OF]->(b)""",
            rows=cps,
        )
        n = s.run("MATCH ()-[r:SUBSIDIARY_OF]->() RETURN count(r) AS n").single()["n"]
    log.info("Neo4j: %s desks, %s banks, %s counterparties, %s SUBSIDIARY_OF links",
             len(desks), len(banks), len(cps), n)


def run(use_gleif: bool = True) -> None:
    entities = refdata.load_entities()
    counterparties = refdata.fictional_counterparties(entities)
    if use_gleif:
        counterparties = refdata.gleif_subsidiaries(entities) + counterparties
    refdata.check_allowlisted(counterparties, entities)

    with connections.postgres() as conn, connections.neo4j_driver() as driver:
        seed_postgres(conn, counterparties)
        seed_neo4j(conn, driver, entities)
