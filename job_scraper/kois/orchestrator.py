from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy.orm import Session

from job_scraper.kois.clustering import cluster_records
from job_scraper.kois.config import get_settings
from job_scraper.kois.digest import send_digest_items
from job_scraper.kois.domain import RawIngestionItem
from job_scraper.kois.extraction import RecordExtractor
from job_scraper.kois.ingestion.imap_adapter import fetch_imap_items
from job_scraper.kois.ingestion.scraper_adapter import jobs_to_raw_items
from job_scraper.kois.repository import (
    create_extracted_record,
    get_extracted_record_for_raw_source,
    upsert_raw_source_item,
)
from job_scraper.models import Job
from job_scraper.slack_poster import SlackPoster
from job_scraper.summarizer import JobDescriptionSummarizer

logger = logging.getLogger(__name__)


def _record_matches_raw_content(raw_item, record) -> bool:
    extracted_data = record.extracted_data or {}
    return extracted_data.get("raw_content_hash") == raw_item.content_hash


def run_kois_pipeline(
    session: Session,
    scraped_jobs: Iterable[Job],
) -> dict:
    settings = get_settings()
    ingestion_items: list[RawIngestionItem] = []
    ingestion_items.extend(jobs_to_raw_items(scraped_jobs))
    ingestion_items.extend(fetch_imap_items(settings))

    raw_items = [upsert_raw_source_item(session, item) for item in ingestion_items]

    summarizer = (
        JobDescriptionSummarizer(optional=True)
        if settings.gemini_api_key
        else None
    )
    extractor = RecordExtractor(summarizer=summarizer)
    records = []
    for raw_item in raw_items:
        existing_record = get_extracted_record_for_raw_source(session, raw_item.id)
        if existing_record and _record_matches_raw_content(raw_item, existing_record):
            records.append(existing_record)
            continue
        try:
            payload = extractor.extract(raw_item)
            record = create_extracted_record(session, payload)
            records.append(record)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Extraction failed for raw source %s", raw_item.id)
            raw_item.extraction_error = str(exc)
            session.flush()

    clusters = cluster_records(session, records)
    slack = SlackPoster(optional=True)
    digests = send_digest_items(
        session=session,
        clusters=clusters,
        slack=slack,
        live_posting=settings.run_live_slack,
        channel=settings.slack_channel,
    )
    session.commit()
    return {
        "raw_items": len(raw_items),
        "records": len(records),
        "clusters": len({cluster.id for cluster in clusters}),
        "digests": len(digests),
    }
