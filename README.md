## KOIS Phase 1 Foundation

This repository now implements the KOIS Phase 1 foundation: provenance-first ingestion and clustering of assignment opportunities from broker scrapers and `oppdrag@kynd.no` (IMAP), with conservative Slack digest output backed by stored evidence.

Per run pipeline:

1. scrape broker portals in parallel (`Mercell`, `Verama`, `Folq`, `Emagine`, `Witted`)
2. ingest IMAP mailbox items from `oppdrag@kynd.no`
3. persist immutable raw source evidence (`raw_source_items`)
4. extract structured records (`extracted_records`)
5. cluster likely duplicates with source comparisons (`opportunity_clusters`, `source_comparisons`)
6. create review states (`review_states`) and conservative digest items (`digest_items`)

### Requirements

- Python 3.12+
- PostgreSQL reachable via `DATABASE_URL`
- Playwright Chromium for scraping

### Environment Variables

Core:

- `DATABASE_URL` (example: `postgresql+psycopg://postgres:postgres@localhost:5432/kois`)
- `RUN_LIVE_SLACK` (`false` by default; set `true` to post live)
- `SLACK_CHANNEL` (`job-posting` default)

Integrations:

- `GEMINI_API_KEY` (optional; summarization/extraction enhancement)
- `SLACK_TOKEN` (required only when `RUN_LIVE_SLACK=true`)
- `{PLATFORM}_USERNAME` / `{PLATFORM}_PASSWORD` for each scraper

IMAP (`oppdrag@kynd.no`):

- `IMAP_HOST`
- `IMAP_PORT` (default `993`)
- `IMAP_USERNAME`
- `IMAP_PASSWORD`
- `IMAP_MAILBOX` (default `INBOX`)
- `IMAP_SINCE_UID` (default `1`)
- `IMAP_SOURCE_NAME` (default `oppdrag@kynd.no`)

### Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m playwright install chromium
```

### Run KOIS Pipeline

```bash
python -m job_scraper.main
```

### Review API (basic queue/archive surface)

```bash
uvicorn job_scraper.kois.review_api:app --reload
```

Useful endpoints:

- `GET /health`
- `GET /clusters`
- `GET /clusters?q=<search>`
- `GET /review-queue`
- `PATCH /clusters/{cluster_id}/status` with `auto_accepted`, `needs_review`, `manually_merged`, `manually_split`, `ignored`, `watch_only`

### Checks

```bash
ruff check .
pytest
```

### Notes

- Raw evidence is preserved even when extraction fails.
- Deduplication is cluster-based; source records are retained.
- Slack digest output is driven by persisted cluster state, not transient scraper output.
