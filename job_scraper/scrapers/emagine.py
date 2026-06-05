from job_scraper.scrapers.base import JobScraper
from playwright.async_api import Page
from typing import List

from job_scraper.models import Job, JobOverview


class EmagineScraper(JobScraper):
    base_url = "https://emagine.no"
    job_platform = "Emagine"

    async def _login(self, page: Page): ...

    async def _parse_job_overview(self, page: Page) -> List[JobOverview]:
        await page.goto(
            f"{self.base_url}/konsulenter/freelance-jobs/",
            wait_until="domcontentloaded",
        )
        await page.wait_for_timeout(4000)

        job_list_el = await page.query_selector_all("article")

        jobs: List[JobOverview] = []
        for job_listing in job_list_el:
            job_href = await job_listing.query_selector('a[class="single-job"]')
            job_uri = await job_href.get_attribute("href")

            job_title_el = await job_listing.query_selector('h2[class="title"]')
            job_title = await job_title_el.text_content()

            start_date = await job_listing.query_selector('div[class="start-date"]')
            converted_date = await start_date.query_selector('span[id="convertedDate"]')
            date = await start_date.text_content()
            if converted_date is not None:
                date = await converted_date.text_content()
            delivery_date = date.strip().split("\n")[-1].strip()

            jobs.append(
                JobOverview(
                    title=job_title, job_uri=job_uri, delivery_date=delivery_date
                )
            )

        self.logging.info(f"Found {len(jobs)} jobs from {self.job_platform}")
        return jobs

    async def _traverse_job_pages(
        self, page: Page, job_overviews: List[JobOverview]
    ) -> List[Job]:
        jobs: List[Job] = []
        for job_overview in job_overviews:
            await page.goto(
                job_overview.job_uri,
                wait_until="domcontentloaded",
            )

            description = await page.query_selector('div[class="single-job-group"]')
            description_text = await description.text_content()

            jobs.append(
                Job(
                    job_overview=job_overview,
                    description=description_text,
                    platform=self.job_platform,
                )
            )
        return jobs
