## KOIS Phases 1-3

This repository implements KOIS as a provenance-first opportunity intelligence pipeline:
- Phase 1 foundation (ingestion, extraction, clustering, review states, digest persistence, operator inbox UI)
- Phase 2 market intelligence (agreement signals, gap discovery, analytics endpoints)
- Phase 3 sales filtering (role classification, availability-aware relevance scoring, configurable digest thresholds/cadence, relevant-opportunity API view)

Per run pipeline:

1. scrape broker portals in parallel (`Mercell`, `Verama`, `Folq`, `Emagine`, `Witted`) unless skipped
2. ingest IMAP mailbox items (one or more assignment addresses)
3. persist immutable raw source evidence (`raw_source_items`)
4. extract structured records (`extracted_records`)
5. cluster likely duplicates with source comparisons (`opportunity_clusters`, `source_comparisons`)
6. classify cluster role fit + relevance against lightweight availability profile
7. create review states (`review_states`) and conservative digest items (`digest_items`)

### Requirements

- Python 3.12+
- PostgreSQL reachable via `DATABASE_URL`
- Playwright Chromium for scraping (not required for `--email-only` runs)

### Environment Variables

Core:

- `DATABASE_URL` (example: `postgresql+psycopg://postgres:postgres@localhost:5432/kois`)
- `KOIS_REVIEW_TOKEN` (shared secret for `/ui` and API access; empty disables auth)
- `KOIS_SKIP_SCRAPERS` (`true` to skip broker scrapers)
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
- `{PLATFORM}_USERNAME` / `{PLATFORM}_PASSWORD` for each scraper (missing creds skip that scraper)

IMAP (single mailbox fallback):

- `IMAP_HOST`
- `IMAP_PORT` (default `993`)
- `IMAP_USERNAME`
- `IMAP_PASSWORD`
- `IMAP_MAILBOX` (default `INBOX`)
- `IMAP_SINCE_UID` (default `1`; used only until a persisted cursor exists)
- `IMAP_SOURCE_NAME` (default `oppdrag@kynd.no`)

IMAP (multiple mailboxes):

- `IMAP_ACCOUNTS_JSON` — JSON array of `{host, username, password, mailbox?, source_name?, port?, since_uid?}`. When set, it replaces the scalar `IMAP_*` fallback.

See `.env.example` for a host-ready template.

### Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install ".[dev]"
python -m playwright install chromium
```

### Run KOIS Pipeline

```bash
python -m job_scraper.main
```

Email-only verification (no broker logins):

```bash
python -m job_scraper.main --email-only
```

### Review UI and API

```bash
uvicorn job_scraper.kois.review_api:app --reload
```

UI (bind to loopback in production):

- `/ui` — review inbox, search, ingest counts
- `/ui/clusters/{id}` — sources, comparison, status update
- `/ui/sources` — recent raw source items (confirm IMAP is landing)

Useful API endpoints:

- `GET /health` (checks Postgres)
- `GET /clusters`
- `GET /clusters/{id}`
- `GET /clusters?q=<search>`
- `GET /review-queue`
- `GET /ingest/summary`
- `GET /ingest/sources`
- `GET /opportunities/relevant`
- `PATCH /clusters/{cluster_id}/status` with `auto_accepted`, `needs_review`, `manually_merged`, `manually_split`, `ignored`, `watch_only`
- `GET /analytics/summary`
- `GET /agreement-signals`
- `GET /agreement-gaps`
- `PATCH /agreement-gaps/{gap_id}/status`

Send `Authorization: Bearer $KOIS_REVIEW_TOKEN` when a token is configured.

### Deploy next to Forgejo

Run KOIS as a **separate Docker Compose project** on the same machine as Forgejo. Do not share Forgejo's Postgres or compose file.

```bash
cp .env.example .env
# fill IMAP accounts, KOIS_REVIEW_TOKEN, and DATABASE_URL (host `db`)
docker compose up -d db api
docker compose --profile batch run --rm pipeline python -m job_scraper.main --email-only
```

Confirm ingest in the UI via SSH tunnel:

```bash
ssh -L 8080:127.0.0.1:8080 user@host
# open http://127.0.0.1:8080/ui and /ui/sources
```

Then install the timer (adjust `WorkingDirectory` in `deploy/kois-pipeline.service` to the clone path):

```bash
sudo cp deploy/kois-pipeline.service deploy/kois-pipeline.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kois-pipeline.timer
```

Keep `RUN_LIVE_SLACK=false` until email rows appear in `/ui/sources`. Enable scrapers by unsetting `KOIS_SKIP_SCRAPERS` after IMAP is confirmed.

Nightly KOIS-only backup:

```bash
docker compose exec -T db pg_dump -U kois kois > kois-$(date +%F).sql
```

Git: pull from the Forgejo remote on the host (`git pull && docker compose build && docker compose up -d`). Do not use Forgejo Actions to schedule scrapes on this box.

### Live IMAP verification

1. Set `IMAP_ACCOUNTS_JSON` or scalar `IMAP_*` for each assignment mailbox. Use app passwords, not in git.
2. Keep `KOIS_SKIP_SCRAPERS=true` and `RUN_LIVE_SLACK=false`.
3. Run `python -m job_scraper.main --email-only` or the Compose pipeline command above.
4. Check `/ingest/summary` and `/ui/sources` for `source_type=email`.
5. Only then enable scrapers and, later, live Slack.

### Checks

These are the same commands CI runs. Use them before committing:

```bash
./scripts/check
```

`./scripts/lint` is Ruff only; `./scripts/test` is pytest only. To run lint automatically on every commit:

```bash
./scripts/install-git-hooks
```

### Notes

- Raw evidence is preserved even when extraction fails.
- Deduplication is cluster-based; source records are retained.
- IMAP UID watermarks are stored in `ingest_cursors` so later runs do not rescan the whole mailbox.
- Slack digest output is driven by persisted cluster state, not transient scraper output.
- Phase 3 filtering only affects presentation (digest/API relevance), not archive retention.
