import argparse
import asyncio
import logging
import os
from playwright.async_api import Browser, async_playwright
from typing import List
from dotenv import load_dotenv

from job_scraper.kois.config import get_settings
from job_scraper.kois.db import SessionLocal, create_db_engine
from job_scraper.kois.migrations import run_migrations
from job_scraper.kois.orchestrator import run_kois_pipeline
from job_scraper.models import Job
from job_scraper.scrapers.emagine import EmagineScraper
from job_scraper.scrapers.folq import FolqScraper
from job_scraper.scrapers.mercell import MercellScraper
from job_scraper.scrapers.verama import VeramaScraper
from job_scraper.scrapers.witted import WittedScraper

logging.basicConfig(level=logging.INFO)

SCRAPER_CLASSES = [
    MercellScraper,
    VeramaScraper,
    FolqScraper,
    EmagineScraper,
    WittedScraper,
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the KOIS ingestion pipeline")
    parser.add_argument(
        "--email-only",
        action="store_true",
        help="Skip broker scrapers and ingest configured IMAP accounts only.",
    )
    return parser.parse_args(argv)


def _has_scraper_credentials(job_platform: str) -> bool:
    prefix = job_platform.upper()
    return bool(os.getenv(f"{prefix}_USERNAME") and os.getenv(f"{prefix}_PASSWORD"))


async def run_scrapers() -> List[Job]:
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch()
        scrapers = []
        for scraper_cls in SCRAPER_CLASSES:
            platform = scraper_cls.job_platform
            if not _has_scraper_credentials(platform):
                logging.warning(
                    "Skipping %s: missing %s_USERNAME or %s_PASSWORD",
                    platform,
                    platform.upper(),
                    platform.upper(),
                )
                continue
            scrapers.append(scraper_cls(browser))

        if not scrapers:
            await browser.close()
            return []

        tasks = [scraper.scrape_jobs() for scraper in scrapers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scraped_jobs = []
        for scraper, result in zip(scrapers, results):
            if isinstance(result, Exception):
                logging.error(
                    f"Could not scrape {scraper.job_platform}: error {result}"
                )
            else:
                scraped_jobs.extend(result)
        await browser.close()
        return scraped_jobs


async def main(argv: list[str] | None = None):
    load_dotenv()
    args = parse_args(argv)
    settings = get_settings()
    skip_scrapers = args.email_only or settings.skip_scrapers
    if skip_scrapers:
        logging.info("Skipping broker scrapers (email-only run)")
        scraped_jobs: List[Job] = []
    else:
        scraped_jobs = await run_scrapers()
    engine = create_db_engine()
    run_migrations(engine)
    with SessionLocal() as session:
        result = run_kois_pipeline(session=session, scraped_jobs=scraped_jobs)
    logging.info("KOIS run complete: %s", result)


if __name__ == "__main__":
    asyncio.run(main())
