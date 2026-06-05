from job_scraper.scrapers.base import JobScraper
from playwright.async_api import Page
from typing import List

from job_scraper.models import Job, JobOverview

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class FolqScraper(JobScraper):
    base_url = "https://app.folq.com"
    job_platform: str = "Folq"

    async def _login(self, page: Page) -> None:
        await page.goto("https://app.folq.com/login")
        await page.fill("input[type='email']", self.username)
        await page.fill("input[type='password']", self.password)
        await page.click("button[type='submit']")
        # Folq redirect is slow
        await page.wait_for_timeout(5000)

    async def _traverse_job_pages(
        self, page: Page, job_overviews: List[JobOverview]
    ) -> List[Job]:
        jobs: List[Job] = []

        for job_overview in job_overviews:
            await page.goto(
                job_overview.job_uri,
                wait_until="networkidle",
            )

            description_el = await page.query_selector(
                'div[class="hc spacing-8-8 s c wf ct cl"]'
            )
            description_text = await description_el.text_content()

            jobs.append(
                Job(
                    job_overview=job_overview,
                    description=description_text,
                    platform=self.job_platform,
                )
            )

        return jobs

    async def _parse_job_overview(self, page: Page) -> List[JobOverview]:
        await page.goto(
            f"{self.base_url}/assignments/all?sorting=by-deadline",
            wait_until="domcontentloaded",
        )

        # Filter on jobs in Norway
        await page.select_option(
            '//*[@id="main-content"]/div/div[2]/div/div[2]/div/div[1]/div[1]/div[2]/div[2]/select',
            "norge",
        )

        job_list_el = await page.query_selector_all(
            '//*[@id="main-content"]/div/div[2]/div/div[2]/div/div[2]/div'
        )

        jobs: List[JobOverview] = []
        for job_listing in job_list_el:
            job_title_and_href_el = await job_listing.query_selector("a")
            job_href = await job_title_and_href_el.get_attribute("href")

            job_title = await job_title_and_href_el.text_content()

            company = await job_listing.query_selector(
                'div[class="spacing-5-5 font-size-14 ff-helvetica-neuehelveticaarialsans-serif fc-60-60-60-255 w3 s p wf"]'
            )

            company_text = await company.text_content()

            due_date_el = await job_listing.query_selector(
                'div[class="hc cptr fc-66-156-218-255 s e wf ccx ccy sbt notxt focusable"]'
            )
            due_date_text = (
                await due_date_el.text_content() if due_date_el else "Snarest"
            )

            jobs.append(
                JobOverview(
                    title=job_title,
                    job_uri=self.base_url + job_href,
                    company=company_text,
                    delivery_date=due_date_text,
                )
            )

        logging.info(f"Found {len(jobs)} jobs from {self.job_platform}")
        return jobs
