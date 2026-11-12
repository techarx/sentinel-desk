# services/ingest-edgar — SEC filings into Postgres and OpenSearch

For each allowlisted bank (`config/entities.yaml`), loads the latest 10-Ks and 10-Qs:

```
EDGAR ──► download (cached) ──► HTML → text ──► split into Items ──► chunk ──► embed ──► Postgres + OpenSearch
```

| Module | Job |
|---|---|
| `edgar.py` | SEC client: User-Agent with contact email, ≤5 requests/s, retries, download cache |
| `html_text.py` | Inline-XBRL HTML → text; hidden XBRL facts removed, table rows kept as `cell \| cell` |
| `items.py` | Finds Items 1A, 7, 7A, 8 (10-Q items mapped to the same numbers); falls back to title headings and the EX-13 annual-report exhibit |
| `chunker.py` | ~450-token chunks, ≤510, ~50-token sentence overlap, small tails merged, never crossing a section |
| `embed.py` | `bge-small-en-v1.5` (384 dims) via fastembed / ONNX Runtime, baked into the image |
| `store.py` | Postgres as `ingest_writer` (one transaction per filing); OpenSearch `chunks` index; reconcile repairs gaps |

## Running

In the cluster it is the `ingest-edgar` CronJob (daily at 06:00 UTC). On the dev machine:

```bash
make ingest          # run now and follow the log
make ingest-status   # counts per bank in Postgres and OpenSearch
```

Re-runs skip filings already loaded (by SEC accession number) and never re-download (cache volume).

Options: `--tickers BAC WFC` (subset), `--tenk 3 --tenq 3` (how many per bank), `--dry-run` (download, split and chunk only).

## Rules it follows

- **Allowlist only**: tickers outside `config/entities.yaml` are refused (tested).
- **SEC fair access**: identifies itself; the contact comes from the `sec-edgar` Secret, never from Git.
- **Least privilege**: the `ingest_writer` role can write filings and chunks but cannot read trades or customers.

## Tests

```bash
pip install -r services/ingest-edgar/requirements-dev.txt
python -m pytest services/ingest-edgar/tests
```

They use synthetic filings, so no SEC text is stored in the repo.
