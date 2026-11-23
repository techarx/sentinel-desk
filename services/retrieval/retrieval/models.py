"""Shared types: search filters and results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Filters:
    """Metadata filters. Empty = no restriction."""

    tickers: tuple[str, ...] = ()
    years: tuple[int, ...] = ()
    forms: tuple[str, ...] = ()  # "10-K", "10-Q"
    items: tuple[str, ...] = ()  # "1A", "7", "7A", "8"

    @classmethod
    def parse(cls, tickers: str = "", years: str = "", forms: str = "", items: str = "") -> Filters:
        """From comma-separated strings, e.g. Filters.parse(tickers="BAC,WFC", years="2025")."""

        def split(value: str) -> list[str]:
            return [v.strip() for v in value.split(",") if v.strip()]

        return cls(
            tickers=tuple(t.upper() for t in split(tickers)),
            years=tuple(int(y) for y in split(years)),
            forms=tuple(f.upper() for f in split(forms)),
            items=tuple(i.upper() for i in split(items)),
        )

    def describe(self) -> str:
        parts = [f"{name}={','.join(map(str, values))}"
                 for name, values in (("ticker", self.tickers), ("year", self.years),
                                      ("form", self.forms), ("item", self.items)) if values]
        return " ".join(parts) or "none"


@dataclass
class Hit:
    chunk_id: int
    score: float
    ticker: str
    fiscal_year: int
    form: str
    item: str
    text: str
    # For hybrid results: the rank this chunk had in each input list (None = not in that list).
    ranks: dict[str, int | None] = field(default_factory=dict)

    def label(self) -> str:
        return f"{self.ticker} {self.fiscal_year} {self.form} item {self.item}"
