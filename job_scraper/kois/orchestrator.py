from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy.orm import Session

from job_scraper.kois.agreement_signals import sync_procurement_agreement_signal
from job_scraper.kois.clustering import cluster_records, refresh_clusters
from job_scraper.kois.config import get_settings
from job_scraper.kois.digest import send_digest_items
from job_scraper.kois.domain import RawIngestionItem
from job_scraper.kois.extraction import RecordExtractor
from job_scraper.kois.gaps import discover_missing_agreement_gaps
from job_scraper.kois.ingestion.imap_adapter import fetch_imap_items
from job_scraper.kois.ingestion.procurement_adapter import fetch_procurement_items
from job_scraper.kois.ingestion.scraper_adapter import jobs_to_raw_items
from job_scraper.kois.repository import (
    create_extracted_record,
    detach_record_cluster_sources,
    get_extracted_record_for_raw_source,
    list_clusters_with_unsent_digests,
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
    ingestion_items.extend(fetch_procurement_items(settings))

    raw_items = [upsert_raw_source_item(session, item) for item in ingestion_items]

    summarizer = (
        JobDescriptionSummarizer(optional=True)
        if settings.gemini_api_key
        else None
    )
    extractor = RecordExtractor(summarizer=summarizer)
    records = []
    record_by_raw_source_id: dict[int, object] = {}
    clusters_from_failed_extraction: list = []
    for raw_item in raw_items:
        existing_record = get_extracted_record_for_raw_source(session, raw_item.id)
        if existing_record and _record_matches_raw_content(raw_item, existing_record):
            records.append(existing_record)
            record_by_raw_source_id[raw_item.id] = existing_record
            continue
        try:
            payload = extractor.extract(raw_item)
            record = create_extracted_record(session, payload)
            records.append(record)
            record_by_raw_source_id[raw_item.id] = record
        except Exception as exc:  # noqa: BLE001
            logger.exception("Extraction failed for raw source %s", raw_item.id)
            raw_item.extraction_error = str(exc)
            session.flush()
            if existing_record is not None:
                clusters_from_failed_extraction.extend(
                    detach_record_cluster_sources(session, existing_record)
                )

    touched_clusters = cluster_records(session, records)
    for raw_item in raw_items:
        record = record_by_raw_source_id.get(raw_item.id)
        if record is None:
            continue
        sync_procurement_agreement_signal(session, raw_item=raw_item, record=record)
    discovered_gaps = discover_missing_agreement_gaps(
        session,
        min_cluster_hits=getattr(settings, "agreement_gap_min_cluster_hits", 2),
    )
    if clusters_from_failed_extraction:
        refresh_clusters(session, clusters_from_failed_extraction)
        touched_clusters = [*touched_clusters, *clusters_from_failed_extraction]
    pending_clusters = list_clusters_with_unsent_digests(session)
    clusters = list(
        {cluster.id: cluster for cluster in [*touched_clusters, *pending_clusters]}.values()
    )
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
        "clusters": len({cluster.id for cluster in touched_clusters}),
        "gaps": len(discovered_gaps),
        "digests": len(digests),
    }
