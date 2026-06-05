## Job Scraper

Async Python batch job that scrapes freelance assignments from Mercell, Verama, Folq, Emagine, and Witted, then posts only new listings to Slack.

Flow per run:
- scrape all sources in parallel with Playwright
- diff against local state in `jobs.json`
- summarize new descriptions with Gemini
- post to Slack channel `job-posting`
- persist newly seen jobs to `jobs.json`

Required environment variables:
- `GEMINI_API_KEY`
- `SLACK_TOKEN`
- `{PLATFORM}_USERNAME` and `{PLATFORM}_PASSWORD` for scraper platforms (current code path expects these for all configured scrapers)

Setup and run:
```bash
uv sync
uv run playwright install chromium
cd job_scraper
uv run python main.py
```
