from job_scraper.scrapers.base import JobScraper
from playwright.async_api import Page
from typing import List

from job_scraper.models import Job, JobOverview


class WittedScraper(JobScraper):
    base_url = "https://wittedpartners.com"
    job_platform = "Witted"

    async def _login(self, page: Page): ...

    async def _parse_job_overview(self, page: Page) -> List[JobOverview]:
        await page.goto(
            f"{self.base_url}/projects?location=norway",
            wait_until="domcontentloaded",
        )
        await page.wait_for_timeout(2000)

        job_list_el = await page.query_selector_all("li[data-list-item]")

        jobs: List[JobOverview] = []
        for job_listing in job_list_el:
            job_title_el = await job_listing.query_selector("h2")
            job_title = await job_title_el.text_content()

            job_href = await job_listing.query_selector("a[href]")
            job_uri = await job_href.get_attribute("href")

            job_description_el = await job_listing.query_selector("p")
            job_description = await job_description_el.text_content()

            jobs.append(
                JobOverview(
                    title=job_title, job_uri=job_uri, description=job_description
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

            description = await page.query_selector(
                'div[class="wysiwyg ingress col-span-12 mp:col-span-8 mp:col-start-5"]'
            )
            description_text = await description.text_content()

            jobs.append(
                Job(
                    job_overview=job_overview,
                    description=description_text,
                    platform=self.job_platform,
                )
            )
        return jobs
