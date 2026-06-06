from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from job_scraper.kois.clustering import cluster_records
from job_scraper.kois.domain import RawIngestionItem
from job_scraper.kois.extraction import RecordExtractor
from job_scraper.kois.repository import (
    create_extracted_record,
    create_or_update_cluster,
    get_extracted_record_for_raw_source,
    upsert_raw_source_item,
)
from job_scraper.kois.schema import Base, ClusterSource, ExtractedRecord, OpportunityCluster, ReviewStatus
from job_scraper.models import Job, JobOverview


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(bind=engine, future=True)


def test_raw_source_upsert_is_idempotent():
    session = _session()
    item = RawIngestionItem(
        source_type="scraper",
        source_name="mercell",
        external_id="id-1",
        raw_body="same-content",
        metadata={"title": "A"},
    )
    first = upsert_raw_source_item(session, item)
    second = upsert_raw_source_item(session, item)
    session.commit()

    assert first.id == second.id


def test_extraction_and_clustering_creates_review_status():
    session = _session()
    extractor = RecordExtractor(summarizer=None)
    job = Job(
        job_overview=JobOverview(
            title="Data Engineer",
            company="Kynd",
            delivery_date="2026-06-30",
            job_uri="https://example.com/jobs/1",
        ),
        description="Build data pipelines",
        platform="Mercell",
    )
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="scraper",
            source_name="mercell",
            external_id="https://example.com/jobs/1",
            raw_body=job.model_dump_json(),
            metadata={"platform": "Mercell"},
        ),
    )
    payload = extractor.extract(raw)
    record = create_extracted_record(session, payload)
    clusters = cluster_records(session, [record])
    session.commit()

    stored_cluster = session.execute(select(OpportunityCluster)).scalar_one()
    assert len(clusters) == 1
    assert stored_cluster.review_status in (
        ReviewStatus.AUTO_ACCEPTED,
        ReviewStatus.NEEDS_REVIEW,
    )
    assert stored_cluster.primary_source_record_id == record.id


def test_extracted_record_is_reused_for_existing_raw_source():
    session = _session()
    extractor = RecordExtractor(summarizer=None)
    job = Job(
        job_overview=JobOverview(
            title="Data Engineer",
            company="Kynd",
            delivery_date="2026-06-30",
            job_uri="https://example.com/jobs/1",
        ),
        description="Build data pipelines",
        platform="Mercell",
    )
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="scraper",
            source_name="mercell",
            external_id="https://example.com/jobs/1",
            raw_body=job.model_dump_json(),
            metadata={"platform": "Mercell"},
        ),
    )
    payload = extractor.extract(raw)
    first_record = create_extracted_record(session, payload)
    session.commit()

    second_record = get_extracted_record_for_raw_source(session, raw.id)
    assert second_record is not None
    assert second_record.id == first_record.id

    clusters_first = cluster_records(session, [first_record])
    clusters_second = cluster_records(session, [second_record])
    session.commit()

    assert session.execute(select(ExtractedRecord)).scalars().all() == [first_record]
    assert len(session.execute(select(ClusterSource)).scalars().all()) == 1
    assert clusters_first[0].id == clusters_second[0].id


def test_create_or_update_cluster_preserves_reviewer_status():
    session = _session()
    cluster = create_or_update_cluster(
        session=session,
        cluster_key="manual-review",
        title="Assignment",
        customer="Kynd",
        confidence=0.7,
        review_status=ReviewStatus.IGNORED,
    )
    session.commit()

    updated = create_or_update_cluster(
        session=session,
        cluster_key="manual-review",
        title="Assignment",
        customer="Kynd",
        confidence=0.95,
        review_status=ReviewStatus.AUTO_ACCEPTED,
    )
    session.commit()

    assert updated.id == cluster.id
    assert updated.review_status == ReviewStatus.IGNORED
    assert updated.confidence == 0.95
