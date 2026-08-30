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

- `KOIS_LLM_PROVIDER` (`anthropic` or `kimi`; optional — auto-selected if only one API key is set)
- `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` (default `claude-sonnet-4-5`)
- `KIMI_API_KEY` or `MOONSHOT_API_KEY` / `KIMI_BASE_URL` (default `https://api.moonshot.ai/v1`) / `KIMI_MODEL` (default `kimi-k2-turbo-preview`)
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

See `.env.example` for the plaintext schema. Runtime `.env` is decrypted with `./scripts/secrets-decrypt` and is gitignored.

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

### Deploy (macOS: M1 now, Mac Mini later)

Same Compose stack on Apple Silicon. Do not share Forgejo's Postgres. Do not put API keys in the Forgejo repo as plaintext.

Prereqs: Docker Desktop, OrbStack, or Colima; `brew install age sops`.

**Secrets (SOPS + age)**

1. Each operator: `./scripts/secrets-keygen` and commit their `age1...` public key in `deploy/age-recipients.txt`.
2. First operator: `cp .env.example .env`, set `POSTGRES_SUPERUSER_PASSWORD` and `KOIS_DB_PASSWORD` with `openssl rand -hex 32`, fill IMAP/LLM/Slack as needed, then `./scripts/secrets-encrypt`.
3. Commit `deploy/secrets.enc.env`. Never commit `.env`.
4. After a new public key is added, an existing operator re-runs `./scripts/secrets-encrypt`.
5. On the host: `./scripts/secrets-decrypt` (writes `.env` mode 600).

**Start**

```bash
./scripts/secrets-decrypt
docker compose up -d db api
./scripts/run-pipeline python -m job_scraper.main --email-only
```

UI is on `http://127.0.0.1:8080/ui`. Keep `KOIS_SKIP_SCRAPERS=true` and `RUN_LIVE_SLACK=false` until `/ui/sources` shows email.

**Schedule (launchd)**

```bash
./scripts/install-launchagents
```

Pipeline every 20 minutes; `pg_dump -Fc` daily at 03:15 into `backups/` (gitignored, 30-day retention). Manual backup: `./scripts/backup-db`. Restore (destructive): `./scripts/restore-db backups/kois-....dump`.

Moving M1 → Mini: copy the git repo, `./scripts/secrets-decrypt`, `docker compose up -d db api`, restore the latest dump, install launch agents. Do not copy Docker volumes between machines.

Linux systemd units remain in `deploy/linux/` if a non-Mac host is used later.

Git: Forgejo (or GitHub) holds code and ciphertext. Pull on the host, then `docker compose build && docker compose up -d`. Do not use Forgejo Actions as the production scheduler.

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
