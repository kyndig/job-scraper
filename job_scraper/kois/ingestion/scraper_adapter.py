from datetime import datetime, timezone
from typing import Iterable

from job_scraper.kois.domain import RawIngestionItem
from job_scraper.kois.utils import content_hash, normalize_text
from job_scraper.models import Job


def _fallback_external_id(job: Job) -> str:
    platform = normalize_text(job.platform) or "unknown"
    title = normalize_text(job.job_overview.title) or "untitled"
    company = normalize_text(job.job_overview.company) or "unknown-company"
    deadline = normalize_text(job.job_overview.delivery_date) or "unknown-deadline"
    body_fingerprint = content_hash(job.model_dump_json())[:16]
    return f"fallback:{platform}:{title}:{company}:{deadline}:{body_fingerprint}"


def jobs_to_raw_items(jobs: Iterable[Job]) -> list[RawIngestionItem]:
    raw_items: list[RawIngestionItem] = []
    now = datetime.now(timezone.utc)
    for job in jobs:
        external_id = job.job_overview.job_uri or _fallback_external_id(job)
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
