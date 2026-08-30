import logging
import os
from abc import ABC, abstractmethod

from playwright.async_api import Browser, BrowserContext, Page

from job_scraper.models import Job, JobOverview

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

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(self.__class__.__module__)

    def _load_credentials(self) -> tuple[str | None, str | None]:
        prefix = self.job_platform.upper()
        username = os.getenv(f"{prefix}_USERNAME")
        password = os.getenv(f"{prefix}_PASSWORD")
        return username, password

    async def scrape_jobs(self) -> list[Job]:
        if not self.username or not self.password:
            self.logger.warning(
                "Skipping %s: missing %s_USERNAME or %s_PASSWORD",
                self.job_platform,
                self.job_platform.upper(),
                self.job_platform.upper(),
            )
            return []

        self.logger.info("Starting %s", self.job_platform)

        context: BrowserContext = await self.browser.new_context()
        page = await context.new_page()

        await self._login(page)
        overviews: list[JobOverview] = await self._parse_job_overview(page)
        jobs: list[Job] = await self._traverse_job_pages(page, overviews)

        await context.close()
        return jobs

    @abstractmethod
    async def _login(self, page: Page): ...

    @abstractmethod
    async def _parse_job_overview(self, page: Page) -> list[JobOverview]: ...

    @abstractmethod
    async def _traverse_job_pages(
        self, page: Page, job_overviews: list[JobOverview]
    ) -> list[Job]: ...
