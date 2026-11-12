"""Turn an EDGAR filing (inline XBRL HTML) into clean text with one block per line.

- Hidden XBRL facts (ix:header, display:none) are removed.
- Tables become one line per row, cells joined with " | ", so numbers keep
  their labels instead of dissolving into a soup of figures.
- Block elements (p, div, li, headings) end lines; inline elements do not,
  so a heading split across several <span>s stays on one line.
"""

from __future__ import annotations

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# Inline XBRL is XHTML; parsing it as HTML is what we want (tolerant of quirks).
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

_BLOCK_TAGS = ["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "center", "blockquote"]
_HIDDEN = re.compile(r"display\s*:\s*none", re.I)
_NOISE_CELLS = {"$", ")", "%", "(", "—", "-"}


def html_to_text(html: bytes) -> str:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "head", "title"]):
        tag.decompose()
    for tag in soup.find_all("ix:header"):
        tag.decompose()
    for tag in soup.find_all(style=_HIDDEN):
        tag.decompose()

    for table in soup.find_all("table"):
        if table.parent is None:  # already replaced as part of an outer table
            continue
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            cells = [c for c in cells if c and c not in _NOISE_CELLS]
            if cells:
                rows.append(" | ".join(cells))
        table.replace_with("\n" + "\n".join(rows) + "\n")

    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")

    text = soup.get_text()
    text = text.replace("\x00", "").replace("\xa0", " ").replace("\u200b", "")
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n"))
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
