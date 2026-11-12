"""Settings and the entity allowlist (config/entities.yaml)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

ENTITIES_FILE = Path(os.environ.get("ENTITIES_FILE", "/app/config/entities.yaml"))


def banks(path: Path = ENTITIES_FILE) -> dict[str, tuple[str, str]]:
    """{ticker: (10-digit CIK, name)} for the allowlisted banks, in allowlist order."""
    data = yaml.safe_load(path.read_text())
    return {b["ticker"].upper(): (f"{int(b['cik']):010d}", b["name"]) for b in data["banks"]}


def allowed_tickers(path: Path = ENTITIES_FILE) -> list[str]:
    """Tickers of the banks whose filings may be ingested, in allowlist order."""
    return list(banks(path))


def check_allowed(requested: list[str], allowed: list[str]) -> list[str]:
    """Return the requested tickers (upper-cased), or raise if any is not allowlisted."""
    wanted = [t.upper() for t in requested]
    rejected = sorted(set(wanted) - set(allowed))
    if rejected:
        raise ValueError(f"Not in the allowlist (config/entities.yaml): {', '.join(rejected)}")
    return wanted
