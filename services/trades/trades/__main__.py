"""python -m trades {seed|generate|consume} [options]"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from prometheus_client import start_http_server


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.WARNING)

    p = argparse.ArgumentParser(prog="trades")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("seed", help="Load desks, books, counterparties, customers")
    s.add_argument("--no-gleif", action="store_true", help="Fictional counterparties only (offline tests)")
    g = sub.add_parser("generate", help="Publish synthetic trades to Redis")
    g.add_argument("--rate", type=float, default=float(os.environ.get("TRADE_RATE", "100")))
    g.add_argument("--duration", type=float, default=0, help="Seconds to run (0 = forever)")
    g.add_argument("--no-bursts", action="store_true")
    g.add_argument("--seed", type=int, default=None, help="Fixed random seed (tests)")
    c = sub.add_parser("consume", help="Consume trades into Postgres and Neo4j")
    c.add_argument("--exit-when-idle", type=float, default=0, help="Stop after N idle seconds (tests)")
    args = p.parse_args(argv)

    from . import connections

    if args.command == "seed":
        from . import seed

        seed.run(use_gleif=not args.no_gleif)
        return 0

    start_http_server(int(os.environ.get("METRICS_PORT", "9100")))  # /metrics for Prometheus
    if args.command == "generate":
        from . import generator

        with connections.postgres() as conn:
            ref = generator.load_refdata(conn)
        generator.run(connections.redis_client(), ref, args.rate, args.duration, not args.no_bursts, args.seed)
        return 0

    from . import consumer

    with connections.postgres() as conn, connections.neo4j_driver() as driver:
        consumer.run(connections.redis_client(), conn, driver, args.exit_when_idle)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
