"""Reference data: desks, books, instruments, counterparties.

Real counterparties come only from GLEIF subsidiaries of the allowlisted banks
(config/entities.yaml). Fictional ones are built from a fixed, made-up word list
with a fixed seed, so every run produces the same names.
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

log = logging.getLogger(__name__)

ENTITIES_FILE = Path(os.environ.get("ENTITIES_FILE", "/app/config/entities.yaml"))
GLEIF_API = "https://api.gleif.org/api/v1"

# (name, region, asset class). Fictional trading desks of the fictional bank.
DESKS: list[tuple[str, str, str]] = [
    ("Rates NY", "AMER", "rates"),
    ("Rates London", "EMEA", "rates"),
    ("FX London", "EMEA", "fx"),
    ("FX Tokyo", "APAC", "fx"),
    ("Credit NY", "AMER", "credit"),
    ("Credit London", "EMEA", "credit"),
    ("Equity Derivatives NY", "AMER", "equity"),
    ("Equity Derivatives HK", "APAC", "equity"),
]
BOOKS_PER_DESK = ("A", "B", "C")

# instrument -> currency, per asset class
INSTRUMENTS: dict[str, dict[str, str]] = {
    "rates": {"UST 2Y": "USD", "UST 10Y": "USD", "UST 30Y": "USD", "SOFR 5Y Swap": "USD", "Bund 10Y": "EUR"},
    "fx": {"EURUSD": "EUR", "USDJPY": "USD", "GBPUSD": "GBP", "USDCAD": "USD", "AUDUSD": "AUD"},
    "credit": {"CDX IG 5Y": "USD", "CDX HY 5Y": "USD", "iTraxx Main 5Y": "EUR", "iTraxx Crossover 5Y": "EUR"},
    "equity": {"SPX Future": "USD", "NDX Future": "USD", "SX5E Future": "EUR", "HSI Future": "HKD"},
}

_NAME_A = ["Granite", "Harbor", "Meridian", "Juniper", "Cobalt", "Alder", "Summit", "Willow", "Basalt",
           "Lantern", "Orchard", "Quarry", "Saffron", "Tundra", "Vantage", "Wren", "Beacon", "Cedar",
           "Delta Ridge", "Ember", "Fjord", "Glacier", "Heron", "Ironwood", "Kestrel", "Lumen"]
_NAME_B = ["Bay", "Crest", "Field", "Gate", "Hill", "Lake", "Point", "River", "Rock", "Stone", "Vale", "Wood"]
_SUFFIX = {
    "hedge_fund": ["Capital Partners LP", "Master Fund Ltd", "Opportunities Fund LP"],
    "asset_manager": ["Asset Management", "Investment Advisors", "Global Investors"],
    "corporate": ["Industries Inc", "Holdings Corp", "Logistics Ltd", "Energy Co"],
    "insurer": ["Insurance Company", "Life Assurance", "Re Ltd"],
    "pension_fund": ["Pension Fund", "Retirement System", "Employees' Pension Plan"],
}
_COUNTRIES = ["US"] * 6 + ["GB"] * 3 + ["DE", "FR", "JP", "CA", "CH", "NL", "SG", "AU", "HK"]


@dataclass(frozen=True)
class Bank:
    ticker: str
    lei: str
    name: str


@dataclass(frozen=True)
class Counterparty:
    name: str
    kind: str
    country: str
    is_fictional: bool
    lei: str | None = None
    parent_lei: str | None = None
    parent_ticker: str | None = None


def load_entities(path: Path = ENTITIES_FILE) -> dict:
    return yaml.safe_load(path.read_text())


def banks(entities: dict) -> list[Bank]:
    return [Bank(b["ticker"].upper(), str(b["lei"]), b["name"]) for b in entities["banks"]]


def fictional_counterparties(entities: dict) -> list[Counterparty]:
    cfg = entities["counterparties"]["fictional"]
    rng = random.Random(cfg["seed"])
    seen: set[str] = set()
    out: list[Counterparty] = []
    while len(out) < cfg["count"]:
        kind = rng.choice(cfg["kinds"])
        name = f"{rng.choice(_NAME_A)} {rng.choice(_NAME_B)} {rng.choice(_SUFFIX[kind])}"
        if name in seen:
            continue
        seen.add(name)
        out.append(Counterparty(name=name, kind=kind, country=rng.choice(_COUNTRIES), is_fictional=True))
    return out


def gleif_subsidiaries(entities: dict, client: httpx.Client | None = None) -> list[Counterparty]:
    """Up to max_per_bank active, issued direct subsidiaries of each allowlisted bank."""
    limit = entities["counterparties"]["real"]["max_per_bank"]
    client = client or httpx.Client(timeout=30, headers={"Accept": "application/vnd.api+json"})
    out: list[Counterparty] = []
    for bank in banks(entities):
        found: list[Counterparty] = []
        url = f"{GLEIF_API}/lei-records/{bank.lei}/direct-children"
        params: dict = {"page[size]": 100, "page[number]": 1}
        while url and len(found) < limit:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            body = resp.json()
            for rec in sorted(body["data"], key=lambda r: r["id"]):
                entity, registration = rec["attributes"]["entity"], rec["attributes"]["registration"]
                if entity.get("status") != "ACTIVE" or registration.get("status") != "ISSUED":
                    continue
                found.append(Counterparty(
                    name=entity["legalName"]["name"],
                    kind="bank_subsidiary",
                    country=(entity["legalAddress"].get("country") or "US")[:2],
                    is_fictional=False,
                    lei=rec["id"],
                    parent_lei=bank.lei,
                    parent_ticker=bank.ticker,
                ))
                if len(found) >= limit:
                    break
            url = body.get("links", {}).get("next")
            params = {}
            time.sleep(1.1)  # GLEIF asks for <= 60 requests/minute
        log.info("GLEIF: %s subsidiaries of %s", len(found), bank.ticker)
        out += found
    return out


def check_allowlisted(counterparties: list[Counterparty], entities: dict) -> None:
    """Every real counterparty must trace back to an allowlisted bank."""
    allowed = {b.lei: b.ticker for b in banks(entities)}
    for cp in counterparties:
        if cp.is_fictional:
            continue
        if allowed.get(cp.parent_lei) != cp.parent_ticker:
            raise ValueError(f"{cp.name} ({cp.lei}) is not a subsidiary of an allowlisted bank")
