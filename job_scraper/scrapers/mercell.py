from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from job_scraper.models import Job, JobOverview
from job_scraper.scrapers.base import JobScraper


class MercellScraper(JobScraper):
    base_url = "https://my.mercell.com"
    job_platform: str = "Mercell"

    async def _login(self, page: Page) -> None:
        await page.goto(self.base_url + "/en/m/logon/default.aspx?auth0done=true")
        await page.get_by_role("textbox").fill(self.username)
        await page.get_by_text("Continue").click()
        await page.locator('//*[@id="password"]').fill(self.password)
        await page.get_by_role("button", name="Continue").click()

    async def _parse_job_overview(self, page: Page) -> list[JobOverview]:
        for attempt in range(3):
            try:
                await page.goto(
                    f"{self.base_url}/m/mts/MyTenders.aspx", wait_until="networkidle"
                )
                break
            except (PlaywrightError, PlaywrightTimeoutError) as e:
                self.logger.error("Error: %s (attempt %s/3)", e, attempt + 1)
        else:
            raise TimeoutError("Cannot load MyTenders.aspx after 3 attempts")

        jobs: list[JobOverview] = []
        nxt_button_selector = 'a[class="nxt"]'
        while True:
            jobs.extend(await self._parse_job_overview_table(page))

            if await page.is_visible(nxt_button_selector, strict=True):
                await page.click(nxt_button_selector)
                await page.wait_for_timeout(2000)
            else:
                # No more pages
                break

        self.logger.info("Found %s jobs from %s", len(jobs), self.job_platform)
        return jobs

    async def _parse_job_overview_table(self, page: Page) -> list[JobOverview]:
        """
        Parses each <tr> in the table's <tbody>, extracting the job data
        from known columns. Returns a list of JobOverview.
        """

        table_selector = "#ctl00_ctl00_commonContent_mainContent_ucTenderList_gwTenders_GridViewTop_GridView"
        table = await page.query_selector(table_selector)
        if not table:
            self.logger.warning("Could not find the table on this page.")
            return []

        # Get all <tr> inside <tbody>
        rows = await table.query_selector_all("tbody > tr")
        results: list[JobOverview] = []

        for row in rows:
            # Skip header rows if they contain <th>
            th_cells = await row.query_selector_all("th")
            if th_cells:
                continue

            # Some rows might be a "pager" or other control row with no data
            # So skip if it does not have 'roworder'
            roworder = await row.get_attribute("roworder")
            if roworder is None:
                continue

            # Grab all <td> in the row
            tds = await row.query_selector_all("td")
            if len(tds) < 7:
                # Not enough columns to parse the data we need
                continue

            # 1) The main column with link and company: column index 4
            main_col = tds[4]
            # - The "title" link is the <a class="hide100pct">
            title_a = await main_col.query_selector("a.hide100pct")
            title_text = ""
            job_href = ""
            if title_a:
                title_text = (await title_a.inner_text() or "").strip()
                job_href = await title_a.get_attribute("href") or ""

            # - The "company" link is the <a class="company-in-grid">
            company_a = await main_col.query_selector("a.company-in-grid")
            company_text = ""
            if company_a:
                # The text inside <a> might contain an icon <svg> plus the name,
                # so we might just do .inner_text() and strip it
                company_text = (await company_a.inner_text() or "").strip()

            # 3) Delivery date: column index 5
            date_el = tds[5]
            delivery_date = (await date_el.inner_text() or "").strip()

            results.append(
                JobOverview(
                    title=title_text,
                    company=company_text,
                    description="",  # or parse from tooltip if needed
                    delivery_date=delivery_date,
                    job_uri=self.base_url + job_href,
                )
            )

        return results

    async def _traverse_job_pages(
        self, page: Page, job_overviews: list[JobOverview]
    ) -> list[Job]:
        jobs: list[Job] = []
        for job_overview in job_overviews:
            await page.goto(
                job_overview.job_uri,
                wait_until="domcontentloaded",
            )
            desc_el = await page.query_selector(
                'div[id="commonContent_mainContent_ucStatus_divDescription"]'
            )
            full_desc = await desc_el.text_content() if desc_el else ""

            jobs.append(
                Job(
                    job_overview=job_overview,
                    description=full_desc,
                    platform=self.job_platform,
                )
            )

        return jobs
