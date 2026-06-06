## KOIS Phases 1-3

This repository implements KOIS as a provenance-first opportunity intelligence pipeline:
- Phase 1 foundation (ingestion, extraction, clustering, review states, digest persistence)
- Phase 2 market intelligence (agreement signals, gap discovery, analytics endpoints)
- Phase 3 sales filtering (role classification, availability-aware relevance scoring, configurable digest thresholds/cadence, relevant-opportunity API view)

Per run pipeline:

1. scrape broker portals in parallel (`Mercell`, `Verama`, `Folq`, `Emagine`, `Witted`)
2. ingest IMAP mailbox items from `oppdrag@kynd.no`
3. persist immutable raw source evidence (`raw_source_items`)
4. extract structured records (`extracted_records`)
5. cluster likely duplicates with source comparisons (`opportunity_clusters`, `source_comparisons`)
6. classify cluster role fit + relevance against lightweight availability profile
7. create review states (`review_states`) and conservative digest items (`digest_items`)

### Requirements

- Python 3.12+
- PostgreSQL reachable via `DATABASE_URL`
- Playwright Chromium for scraping

### Environment Variables

Core:

- `DATABASE_URL` (example: `postgresql+psycopg://postgres:postgres@localhost:5432/kois`)
- `RUN_LIVE_SLACK` (`false` by default; set `true` to post live)
- `SLACK_CHANNEL` (`job-posting` default)
- `DIGEST_MODE` (`balanced`, `high_precision`, `high_recall`)
- `DIGEST_MIN_RELEVANCE_SCORE` (default `0.35`)
- `DIGEST_MIN_SOURCE_CONFIDENCE` (default `0.75`)
- `DIGEST_CADENCE_MINUTES` (default `0`, meaning no cadence gate)
- `AVAILABILITY_PROFILE_JSON` (optional role capacity map, e.g. `{"data_engineering":2,"backend":1}`)
- `ROLE_TAXONOMY_JSON` (optional role-to-keywords map to override defaults)

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
pip install ".[dev]"
python -m playwright install chromium
```

### Run KOIS Pipeline

```bash
python -m job_scraper.main
```

### Review and Intelligence API

```bash
uvicorn job_scraper.kois.review_api:app --reload
```

Useful endpoints:

- `GET /health`
- `GET /clusters`
- `GET /clusters?q=<search>`
- `GET /review-queue`
- `GET /opportunities/relevant`
- `PATCH /clusters/{cluster_id}/status` with `auto_accepted`, `needs_review`, `manually_merged`, `manually_split`, `ignored`, `watch_only`
- `GET /analytics/summary`
- `GET /agreement-signals`
- `GET /agreement-gaps`
- `PATCH /agreement-gaps/{gap_id}/status`

### Checks

```bash
ruff check .
pytest
```

### Notes

- Raw evidence is preserved even when extraction fails.
- Deduplication is cluster-based; source records are retained.
- Slack digest output is driven by persisted cluster state, not transient scraper output.
- Phase 3 filtering only affects presentation (digest/API relevance), not archive retention.
