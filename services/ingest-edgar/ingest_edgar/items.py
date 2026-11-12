"""Split a 10-K or 10-Q into the four sections Sentinel Desk uses.

Sections are stored under the 10-K Item numbers so Phase 2 filters mean the
same thing for both forms:

| item | Section                      | 10-K     | 10-Q              |
|------|------------------------------|----------|-------------------|
| 1A   | Risk Factors                 | Item 1A  | Part II, Item 1A  |
| 7    | MD&A                         | Item 7   | Part I, Item 2    |
| 7A   | Market Risk                  | Item 7A  | Part I, Item 3    |
| 8    | Financial Statements         | Item 8   | Part I, Item 1    |

Two strategies:
1. Item headings ("Item 7. Management's Discussion ...").
2. Title-only headings ("Management's Discussion and Analysis") for filings
   laid out as an annual report, including EX-13 exhibits.

The table of contents repeats every heading, so for each section the
candidate that starts the LONGEST span (up to the next heading) wins.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

ITEMS = ("1A", "7", "7A", "8")
TITLES = {
    "1A": "Risk Factors",
    "7": "Management's Discussion and Analysis",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements",
}
MIN_CHARS = 1500  # shorter "sections" are TOC entries or "incorporated by reference" stubs

_SEP = r"[\s|.:\-–—]*"

# (Item number in that form, title words) per canonical item.
_ITEM_HEADINGS = {
    "10-K": {
        "1A": ("1a", r"risk\s+factors"),
        "7": ("7", r"management'?s\s+discussion"),
        "7A": ("7a", r"quantitative\s+and\s+qualitative"),
        "8": ("8", r"financial\s+statements"),
    },
    "10-Q": {
        "1A": ("1a", r"risk\s+factors"),
        "7": ("2", r"management'?s\s+discussion"),
        "7A": ("3", r"quantitative\s+and\s+qualitative"),
        "8": ("1", r"(?:consolidated\s+)?financial\s+statements"),
    },
}

_ANY_ITEM_LINE = re.compile(rf"^(?:part\s+i{{1,3}}{_SEP})?item{_SEP}\d{{1,2}}[a-c]?\b.*$", re.I | re.M)
_OTHER_BOUNDARY = re.compile(
    r"^(?:signatures?|part\s+i{1,3}\b.{0,80}|exhibits?(?:\s+and\s+financial\s+statement\s+schedules)?)$",
    re.I | re.M,
)

# Title-only headings, used ONLY for sections the Item headings didn't find.
# Each alternative comes from a real filing layout:
#   - the MD&A title may be cut short when it wraps onto a second line (Citi);
#   - Wells Fargo calls its MD&A "Financial Review";
#   - some 10-Qs have no MD&A title in the body at all, it simply begins with
#     "Overview" or "Executive Summary" (BNY);
#   - statement titles vary: "Consolidated Income Statement" (BNY),
#     "Consolidated Statement of Income", "... of Financial Condition".
_TITLE_ONLY = {
    "1A": r"risk\s+factors",
    "7": r"management'?s\s+discussion\s+and\s+analysis"
    r"(?:\s+of\s+financial\s+condition(?:\s+and\s+results\s+of\s+operations?)?)?"
    r"|financial\s+review",
    "7A": r"quantitative\s+and\s+qualitative\s+disclosures?\s+about\s+market\s+risk|market\s+risk\s+management",
    "8": r"(?:consolidated\s+)?financial\s+statements(?:\s+and\s+supplementary\s+data)?"
    r"|consolidated\s+(?:income\s+statements?|balance\s+sheets?)"
    r"|consolidated\s+statements?\s+of\s+(?:income|operations|financial\s+condition)",
}
# Last resort for an MD&A with no title at all. Generic words like "Overview"
# also head subsections elsewhere (e.g. inside Market Risk), so they are only
# tried when the proper titles above found nothing.
_WEAK_MDNA = r"executive\s+summary|overview"


def _title_line(pattern: str) -> re.Pattern[str]:
    optional_item = rf"(?:item{_SEP}\d{{1,2}}[a-c]?{_SEP})?"
    return re.compile(rf"[\W\d]*{optional_item}(?:{pattern})[\W\d]*(?:\(continued\)[\W\d]*)?", re.I)


_TITLE_LINE = {item: _title_line(pattern) for item, pattern in _TITLE_ONLY.items()}
_TITLE_LINE_WEAK = _TITLE_LINE | {"7": _title_line(f"{_TITLE_ONLY['7']}|{_WEAK_MDNA}")}


@dataclass
class Section:
    item: str
    title: str
    text: str
    method: str  # "item_heading", "title_heading" or "ex13"


def normalize(text: str) -> str:
    return text.replace("’", "'").replace("‘", "'")


def _boundaries(text: str) -> list[int]:
    starts = {m.start() for m in _ANY_ITEM_LINE.finditer(text) if len(m.group(0)) <= 200}
    starts |= {m.start() for m in _OTHER_BOUNDARY.finditer(text)}
    starts.add(len(text))
    return sorted(starts)


def _next_boundary(bounds: list[int], pos: int) -> int:
    return bounds[bisect.bisect_right(bounds, pos)]


def split_by_item_headings(text: str, form: str) -> dict[str, Section]:
    text = normalize(text)
    bounds = _boundaries(text)
    found: dict[str, Section] = {}
    for item, (number, title) in _ITEM_HEADINGS[form].items():
        heading = re.compile(rf"^(?:part\s+i{{1,3}}{_SEP})?item{_SEP}{number}{_SEP}{title}", re.I | re.M)
        best = max(
            ((m.start(), _next_boundary(bounds, m.start())) for m in heading.finditer(text)),
            key=lambda span: span[1] - span[0],
            default=None,
        )
        if best and best[1] - best[0] >= MIN_CHARS:
            found[item] = Section(item, TITLES[item], text[best[0] : best[1]].strip(), "item_heading")
    return found


def split_by_title_headings(
    text: str, wanted: list[str], method: str = "title_heading", weak: bool = False
) -> dict[str, Section]:
    """For annual-report layouts: short lines that consist of a section title.

    Running page headers repeat a title on every page, so consecutive hits of
    the same section are merged into one run; a run ends at the next hit of a
    different section or at an Item / Part / Signatures line.
    """
    text = normalize(text)
    hits: list[tuple[int, str | None]] = []
    for line in re.finditer(r"^.+$", text, re.M):
        value = line.group(0)
        if len(value) > 120:
            continue
        for item, pattern in (_TITLE_LINE_WEAK if weak else _TITLE_LINE).items():
            if pattern.fullmatch(value):
                hits.append((line.start(), item))
                break
    hits += [(pos, None) for pos in _boundaries(text)]
    # At the same position a boundary sorts first, so a title line that is also
    # an "Item ..." line ends the previous run and then starts its own.
    hits.sort(key=lambda hit: (hit[0], hit[1] is not None))

    runs: list[tuple[str, int, int]] = []  # (item, start, end)
    current: tuple[str, int] | None = None
    for pos, item in hits:
        if current and item == current[0]:
            continue
        if current:
            runs.append((current[0], current[1], pos))
        current = (item, pos) if item else None

    found: dict[str, Section] = {}
    for item in wanted:
        spans = [(start, end) for run_item, start, end in runs if run_item == item]
        best = max(spans, key=lambda s: s[1] - s[0], default=None)
        if best and best[1] - best[0] >= MIN_CHARS:
            found[item] = Section(item, TITLES[item], text[best[0] : best[1]].strip(), method)
    return found


def split_filing(text: str, form: str, exhibit_text: str | None = None) -> dict[str, Section]:
    """Best-effort split, strongest evidence first:
    Item headings -> title headings -> EX-13 exhibit -> MD&A from "Overview" (last resort)."""

    def missing() -> list[str]:
        return [i for i in ITEMS if i not in sections]

    sections = split_by_item_headings(text, form)
    if missing():
        sections |= split_by_title_headings(text, missing())
    if missing() and exhibit_text:
        sections |= split_by_title_headings(exhibit_text, missing(), method="ex13")
    if "7" not in sections:
        sections |= split_by_title_headings(text, ["7"], weak=True)
    return dict(sorted(sections.items(), key=lambda kv: ITEMS.index(kv[0])))
