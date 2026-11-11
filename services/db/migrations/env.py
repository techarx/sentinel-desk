"""Alembic environment: connects using the standard PG* environment variables.

PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD and PGSSLMODE are the same
variables psql uses. In the cluster they come from the pg-app-credentials Secret.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def database_url() -> URL:
    return URL.create(
        drivername="postgresql+psycopg",
        host=os.environ["PGHOST"],
        port=int(os.environ.get("PGPORT", "5432")),
        database=os.environ.get("PGDATABASE", "sentinel"),
        username=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        query={"sslmode": os.environ.get("PGSSLMODE", "require")},
    )


def run_migrations_online() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        # The migrations are hand-written SQL, so there is no SQLAlchemy model metadata.
        context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline mode is not used in this project.")
run_migrations_online()
