"""Item splitter tests on synthetic filings (no SEC text in the repo)."""

from ingest_edgar.html_text import html_to_text
from ingest_edgar.items import split_by_title_headings, split_filing

FILLER = "The company discussed results in detail. " * 60  # ~2,400 chars, above MIN_CHARS


def _ten_k() -> str:
    # Table of contents first (short spans), then the real sections.
    toc = "\n".join(
        [
            "Item 1A. Risk Factors | 12",
            "Item 7. Management's Discussion and Analysis | 40",
            "Item 7A. Quantitative and Qualitative Disclosures About Market Risk | 80",
            "Item 8. Financial Statements and Supplementary Data | 90",
        ]
    )
    body = "\n".join(
        [
            "Item 1. Business", FILLER,
            "Item 1A. Risk Factors", "RISK " + FILLER,
            "Item 1B. Unresolved Staff Comments", "None.",
            "Item 7. Management’s Discussion and Analysis of Financial Condition", "MDA " + FILLER,
            "Item 7A. Quantitative and Qualitative Disclosures About Market Risk", "MARKET " + FILLER,
            "Item 8. Financial Statements and Supplementary Data", "FS " + FILLER,
            "Item 9. Changes in and Disagreements with Accountants", "None.",
            "SIGNATURES",
        ]
    )
    return toc + "\n" + body


def test_10k_sections_found_by_item_heading_not_toc():
    sections = split_filing(_ten_k(), "10-K")
    assert list(sections) == ["1A", "7", "7A", "8"]
    assert sections["1A"].text.splitlines()[1].startswith("RISK")
    assert sections["7"].text.splitlines()[1].startswith("MDA")
    assert all(s.method == "item_heading" for s in sections.values())


def test_section_stops_at_next_item():
    sections = split_filing(_ten_k(), "10-K")
    assert "MDA" not in sections["1A"].text
    assert "Item 9" not in sections["8"].text


def test_10q_items_map_to_10k_numbers():
    text = "\n".join(
        [
            "PART I", "Item 1. Financial Statements", "FS " + FILLER,
            "Item 2. Management's Discussion and Analysis", "MDA " + FILLER,
            "Item 3. Quantitative and Qualitative Disclosures About Market Risk", "MARKET " + FILLER,
            "Item 4. Controls and Procedures", "Short.",
            "PART II", "Item 1. Legal Proceedings", "LEGAL " + FILLER,
            "Item 1A. Risk Factors", "RISK " + FILLER,
            "Item 6. Exhibits",
        ]
    )
    sections = split_filing(text, "10-Q")
    assert list(sections) == ["1A", "7", "7A", "8"]
    assert "LEGAL" not in sections["8"].text  # Part II Item 1 is not the financial statements
    assert sections["1A"].text.splitlines()[1].startswith("RISK")


def test_short_stub_is_not_a_section():
    text = "\n".join(
        ["Item 7. Management's Discussion and Analysis",
         "Incorporated by reference to the Annual Report.",
         "Item 8. Financial Statements"]
    )
    assert "7" not in split_filing(text, "10-K")


def test_annual_report_layout_uses_title_headings_and_merges_running_headers():
    pages = []
    for _ in range(3):  # the MD&A title repeats as a page header on every page
        pages += ["Management's Discussion and Analysis", "MDA " + FILLER]
    text = "\n".join(["Risk Factors", "RISK " + FILLER, *pages, "Consolidated Balance Sheet", "FS " + FILLER])
    sections = split_by_title_headings(text, ["1A", "7", "8"])
    assert set(sections) == {"1A", "7", "8"}
    assert sections["7"].text.count("MDA ") == 3  # one section spanning all three pages
    assert "RISK" not in sections["7"].text


def test_mdna_title_cut_short_by_line_wrap():
    # The second half of the title wraps onto its own line.
    text = "\n".join(
        ["MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION", "AND RESULTS OF OPERATIONS", "MDA " + FILLER,
         "CONSOLIDATED FINANCIAL STATEMENTS", "FS " + FILLER]
    )
    assert split_filing(text, "10-K")["7"].text.count("MDA ") == 1


def test_mdna_called_financial_review():
    text = "\n".join(["Financial Review", "MDA " + FILLER, "Financial Statements", "FS " + FILLER])
    sections = split_filing(text, "10-K")
    assert "MDA " in sections["7"].text and "FS " not in sections["7"].text


def test_10q_mdna_without_title_starts_at_overview():
    # Contents page names the MD&A; the body just starts at "Overview".
    text = "\n".join(
        ["Table of Contents", "Items 2. and 3. Management's Discussion and Analysis", "Overview | 4",
         "Item 1. Financial Statements: | 47",
         "Overview", "MDA " + FILLER,
         "Item 1. Financial Statements:", "Consolidated Income Statement", "FS " + FILLER]
    )
    sections = split_filing(text, "10-Q")
    assert sections["7"].text.startswith("Overview") and "FS " not in sections["7"].text
    assert "FS " in sections["8"].text


def test_html_heading_split_across_spans_and_table_rows():
    html = (
        b"<html><body>"
        b"<div style='display:none'><ix:header>hidden facts</ix:header></div>"
        b"<p><span>Item 7.</span> <span>Management's Discussion</span></p>"
        b"<table><tr><td>Net income</td><td>$</td><td>1,234</td></tr></table>"
        b"</body></html>"
    )
    text = html_to_text(html)
    assert "hidden facts" not in text
    assert "Item 7. Management's Discussion" in text.splitlines()
    assert "Net income | 1,234" in text.splitlines()
