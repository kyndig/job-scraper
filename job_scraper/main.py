import asyncio
import logging
from playwright.async_api import Browser, async_playwright
from typing import List
from dotenv import load_dotenv

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

async def run_scrapers() -> List[Job]:
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch()
        scrapers = [
            MercellScraper(browser),
            VeramaScraper(browser),
            FolqScraper(browser),
            EmagineScraper(browser),
            WittedScraper(browser),
        ]

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


async def main():
    load_dotenv()
    scraped_jobs: List[Job] = await run_scrapers()
    engine = create_db_engine()
    run_migrations(engine)
    with SessionLocal() as session:
        result = run_kois_pipeline(session=session, scraped_jobs=scraped_jobs)
    logging.info("KOIS run complete: %s", result)


if __name__ == "__main__":
    asyncio.run(main())
