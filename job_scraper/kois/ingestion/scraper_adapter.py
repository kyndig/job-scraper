from datetime import datetime, timezone
from typing import Iterable

from job_scraper.kois.domain import RawIngestionItem
from job_scraper.models import Job


def jobs_to_raw_items(jobs: Iterable[Job]) -> list[RawIngestionItem]:
    raw_items: list[RawIngestionItem] = []
    now = datetime.now(timezone.utc)
    for job in jobs:
        external_id = job.job_overview.job_uri or f"{job.platform}:{job.job_overview.title}"
        metadata = {
            "title": job.job_overview.title,
            "company": job.job_overview.company,
            "delivery_date": job.job_overview.delivery_date,
            "job_uri": job.job_overview.job_uri,
            "platform": job.platform,
        }
        raw_items.append(
            RawIngestionItem(
                source_type="scraper",
                source_name=job.platform or "unknown",
                external_id=external_id,
                raw_body=job.model_dump_json(),
                metadata=metadata,
                received_at=now,
            )
        )
    return raw_items
