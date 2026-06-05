import os
from playwright.async_api import Browser, Page, BrowserContext
from abc import ABC, abstractmethod
from typing import List

from job_scraper.models import Job, JobOverview

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class JobScraper(ABC):
    browser: Browser
    job_platform: str
    base_url: str

    def __init__(self, browser: Browser):
        self.browser = browser
        self.username, self.password = self._load_credentials()

        self.logging = logging

    def _load_credentials(self) -> tuple[str, str]:
        prefix = self.job_platform.upper()
        username = os.getenv(f"{prefix}_USERNAME")
        password = os.getenv(f"{prefix}_PASSWORD")
        if not username or not password:
            raise ValueError(
                f"Missing {prefix}_USERNAME or {prefix}_PASSWORD in environment"
            )
        return username, password

    async def scrape_jobs(self) -> List[Job]:
        logging.info(f"Starting {self.job_platform}")

        context: BrowserContext = await self.browser.new_context()
        page = await context.new_page()

        await self._login(page)
        overviews: List[JobOverview] = await self._parse_job_overview(page)
        jobs: List[Job] = await self._traverse_job_pages(page, overviews)

        await context.close()
        return jobs

    @abstractmethod
    async def _login(self, page: Page): ...

    @abstractmethod
    async def _parse_job_overview(self, page: Page) -> List[JobOverview]: ...

    @abstractmethod
    async def _traverse_job_pages(
        self, page: Page, job_overviews: List[JobOverview]
    ) -> List[Job]: ...
