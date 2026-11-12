"""Grants for the trade_generator role.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-11

The trade generator only needs to know which desks, books and counterparties
exist so it can produce trades that reference them. It publishes to Redis and
never writes to Postgres.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT SELECT ON desks, books, counterparties TO trade_generator;")


def downgrade() -> None:
    op.execute("REVOKE ALL ON desks, books, counterparties FROM trade_generator;")
