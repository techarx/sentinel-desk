"""A polite SEC EDGAR client: identifies itself, rate-limits, retries and caches.

SEC rules (https://www.sec.gov/os/accessing-edgar-data): send a User-Agent with
contact details and stay under 10 requests per second. We stay at 5.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

SEC_WWW = "https://www.sec.gov"
SEC_DATA = "https://data.sec.gov"


@dataclass(frozen=True)
class Filing:
    ticker: str
    cik: str  # zero-padded to 10 digits
    company_name: str
    form: str  # "10-K" or "10-Q"
    accession_no: str  # e.g. 0000070858-25-000023
    filed_at: date
    period_end: date
    primary_document: str

    @property
    def folder_url(self) -> str:
        return f"{SEC_WWW}/Archives/edgar/data/{int(self.cik)}/{self.accession_no.replace('-', '')}"

    @property
    def url(self) -> str:
        return f"{self.folder_url}/{self.primary_document}"

    @property
    def fiscal_year(self) -> int:
        # All allowlisted banks use calendar fiscal years.
        return self.period_end.year

    @property
    def fiscal_period(self) -> str:
        if self.form == "10-K":
            return "FY"
        quarter = (self.period_end.month - 1) // 3 + 1
        if quarter > 3:
            raise ValueError(f"10-Q {self.accession_no} ends in Q4 ({self.period_end})")
        return f"Q{quarter}"


class EdgarClient:
    def __init__(self, user_agent: str, cache_dir: Path, max_requests_per_second: float = 5.0):
        if "@" not in user_agent:
            raise ValueError("SEC requires a contact email in the User-Agent")
        self._http = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=60.0,
            follow_redirects=True,
        )
        self._cache = cache_dir
        self._min_interval = 1.0 / max_requests_per_second
        self._last_request = 0.0

    # -- HTTP ----------------------------------------------------------------

    def _get(self, url: str) -> bytes:
        for attempt in range(6):
            wait = self._last_request + self._min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            response = self._http.get(url)
            if response.status_code == 200:
                return response.content
            if response.status_code in (403, 429, 500, 502, 503, 504):
                backoff = 2**attempt * 2
                log.warning("GET %s -> %s, retrying in %ss", url, response.status_code, backoff)
                time.sleep(backoff)
                continue
            response.raise_for_status()
        raise RuntimeError(f"Giving up on {url}")

    def _get_cached(self, url: str, key: str) -> bytes:
        """Fetch once, then serve from the cache volume (filings never change)."""
        path = self._cache / key
        if path.exists():
            return path.read_bytes()
        data = self._get(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return data

    # -- Lookups -------------------------------------------------------------

    def recent_filings(self, ticker: str, cik: str, n_10k: int, n_10q: int) -> list[Filing]:
        """The latest n 10-Ks and n 10-Qs (amendments excluded), newest first.

        Looked up by CIK (the SEC's permanent company ID) from the allowlist,
        so a ticker change can't silently point at a different company.
        """
        # The main file is not cached: it grows as companies file.
        data = json.loads(self._get(f"{SEC_DATA}/submissions/CIK{cik}.json"))
        name = data["name"]
        # "recent" holds only the newest ~1,000 filings. Large banks file
        # thousands of structured-note prospectuses, so for them that can be
        # less than a year; older filings are in extra pages (which never
        # change, so those are cached).
        pages = [data["filings"]["recent"]]
        extra = [f["name"] for f in data["filings"].get("files", [])]

        wanted = {"10-K": n_10k, "10-Q": n_10q}
        found: list[Filing] = []
        while pages:
            page = pages.pop(0)
            for i, form in enumerate(page["form"]):
                if wanted.get(form, 0) <= 0 or not page["reportDate"][i]:
                    continue
                wanted[form] -= 1
                found.append(
                    Filing(
                        ticker=ticker,
                        cik=cik,
                        company_name=name,
                        form=form,
                        accession_no=page["accessionNumber"][i],
                        filed_at=date.fromisoformat(page["filingDate"][i]),
                        period_end=date.fromisoformat(page["reportDate"][i]),
                        primary_document=page["primaryDocument"][i],
                    )
                )
            if any(n > 0 for n in wanted.values()) and extra:
                page_file = extra.pop(0)
                url = f"{SEC_DATA}/submissions/{page_file}"
                pages.append(json.loads(self._get_cached(url, f"submissions/{page_file}")))
        return found

    def document(self, filing: Filing) -> bytes:
        return self._get_cached(filing.url, f"filings/{filing.accession_no}/{filing.primary_document}")

    def exhibit(self, filing: Filing, exhibit_type: str) -> bytes | None:
        """An exhibit's HTML (e.g. EX-13, the annual report some banks file their 10-K content in)."""
        index = self._get_cached(
            f"{filing.folder_url}/{filing.accession_no}-index.htm",
            f"filings/{filing.accession_no}/index.htm",
        )
        soup = BeautifulSoup(index, "lxml")
        for row in soup.select("table.tableFile tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            doc_type = cells[3].get_text(strip=True).upper()
            link = cells[2].find("a")
            if link and re.match(rf"^{re.escape(exhibit_type)}\b", doc_type):
                name = link.get_text(strip=True).split()[0]
                if name.lower().endswith((".htm", ".html")):
                    return self._get_cached(f"{filing.folder_url}/{name}", f"filings/{filing.accession_no}/{name}")
        return None
