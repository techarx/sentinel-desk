"""Connections, configured from environment variables set by the Kubernetes manifests."""

from __future__ import annotations

import os

import psycopg
import redis
from neo4j import Driver, GraphDatabase


def postgres() -> psycopg.Connection:
    # autocommit: each `with conn.transaction()` block is a real, committed transaction.
    # PGHOST, PGUSER, PGPASSWORD, PGDATABASE, PGSSLMODE come from the environment.
    return psycopg.connect("", autocommit=True)


def redis_client() -> redis.Redis:
    return redis.Redis(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        password=os.environ["REDIS_PASSWORD"],
        decode_responses=False,
        socket_timeout=30,
    )


def neo4j_driver() -> Driver:
    # NEO4J_AUTH is "user/password": the same value the neo4j-auth Secret holds for the Neo4j chart.
    user, password = os.environ["NEO4J_AUTH"].split("/", 1)
    return GraphDatabase.driver(os.environ.get("NEO4J_URI", "bolt://neo4j:7687"), auth=(user, password))
