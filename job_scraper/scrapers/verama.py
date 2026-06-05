from job_scraper.scrapers.base import JobScraper
from playwright.async_api import Page
from typing import List

from job_scraper.models import Job, JobOverview

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class VeramaScraper(JobScraper):
    base_url = "https://app.verama.com/app"
    job_platform: str = "Verama"

    async def _login(self, page: Page) -> None:
        await page.goto("https://app.verama.com/auth?tab=login")
        await page.fill("input[name='username']", self.username)
        await page.fill("input[name='password']", self.password)
        await page.get_by_role("button", name="Log in").click()

    async def _traverse_job_pages(
        self, page: Page, job_overviews: List[JobOverview]
    ) -> List[Job]:
        jobs: List[Job] = []
        for job_overview in job_overviews:
            await page.goto(
                job_overview.job_uri,
                wait_until="domcontentloaded",
            )
            deadline_locator = page.locator(
                "//span[text()='Application deadline']/following-sibling::span[1]"
            )

            deadline_text = await deadline_locator.inner_text()
            deadline = deadline_text.split("(")[0].strip()
            job_overview.delivery_date = deadline

            company_locator = page.locator(
                "//span[text()='Client']/following-sibling::span[1]"
            )
            company = await company_locator.text_content()
            job_overview.company = company

            assignment_description_locator = await page.query_selector(
                "div.job-request-detail__section"
            )
            description = await assignment_description_locator.text_content()

            jobs.append(
                Job(
                    job_overview=job_overview,
                    description=description,
                    platform=self.job_platform,
                )
            )

        return jobs

    async def _parse_job_overview(self, page: Page) -> List[JobOverview]:
        # https://app.verama.com/app/job-requests
        await page.goto(
            f"{self.base_url}/job-requests?page=0&size=20&sortConfig=%5B%7B%22sortBy%22%3A%22firstDayOfApplications%22%2C%22order%22%3A%22DESC%22%7D%5D&filtersConfig=%7B%22location%22%3A%7B%22id%22%3Anull%2C%22signature%22%3A%22%22%2C%22city%22%3A%22Oslo%22%2C%22country%22%3A%22Norway%22%2C%22name%22%3A%22Oslo%2C%20Norway%22%2C%22locationId%22%3A%22here%3Acm%3Anamedplace%3A20421988%22%2C%22countryCode%22%3A%22NOR%22%2C%22suggestedPhoneCode%22%3A%22NO%22%7D%2C%22remote%22%3A%5B%5D%2C%22query%22%3A%22%22%2C%22skillRoleCategories%22%3A%5B%5D%2C%22frequency%22%3A%22DAILY%22%2C%22radius%22%3A20000%2C%22dedicated%22%3Afalse%2C%22originIds%22%3A%5B%5D%2C%22favouritesOnly%22%3Afalse%2C%22recommendedOnly%22%3Afalse%2C%22languages%22%3A%5B%5D%2C%22level%22%3A%5B%5D%2C%22skillIds%22%3A%5B%5D%2C%22skills%22%3A%5B%5D%7D",
            wait_until="networkidle"
        )
        
        await page.wait_for_timeout(2000)

        job_sections = await page.query_selector_all('a[class="route-section"]')

        if not job_sections:
            self.logging.info(f"Could not find any job listings for {self.job_platform}")
            return []

        jobs: List[JobOverview] = []
        for job_section in job_sections:
            job_uri = await job_section.get_attribute("href")

            job_title_el = await job_section.query_selector(
                "span.job-request-record__header"
            )
            job_title = await job_title_el.text_content()

            jobs.append(JobOverview(title=job_title, job_uri=self.base_url + job_uri))

        logging.info(f"Found {len(jobs)} jobs from {self.job_platform}")
        return jobs
