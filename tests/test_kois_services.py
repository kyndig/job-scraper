from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from job_scraper.kois.clustering import cluster_records
from job_scraper.kois.digest import cluster_to_payload
from job_scraper.kois.domain import RawIngestionItem
from job_scraper.kois.extraction import RecordExtractor, make_cluster_key
from job_scraper.kois.repository import (
    attach_cluster_source,
    create_digest_item,
    create_extracted_record,
    create_or_update_cluster,
    get_extracted_record_for_raw_source,
    mark_digest_sent,
    upsert_raw_source_item,
)
from job_scraper.kois.schema import (
    Base,
    ClusterSource,
    DigestItem,
    ExtractedRecord,
    OpportunityCluster,
    RawSourceItem,
    ReviewStatus,
    SourceComparison,
)
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


def test_refresh_comparisons_is_idempotent():
    session = _session()
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="scraper",
            source_name="mercell",
            external_id="id-1",
            raw_body="raw-1",
        ),
    )
    record_a = create_extracted_record(
        session,
        {
            "raw_source_item_id": raw.id,
            "title": "Assignment A",
            "customer": "Kynd",
            "broker": "mercell",
            "source_url": "https://example.com/a",
            "deadline": "2026-06-30",
            "description": "desc",
            "summary": "sum",
            "extracted_data": {},
            "extraction_confidence": 0.95,
        },
    )
    record_b = create_extracted_record(
        session,
        {
            "raw_source_item_id": raw.id,
            "title": "Assignment B",
            "customer": "Kynd",
            "broker": "email",
            "source_url": "https://example.com/a",
            "deadline": "2026-06-30",
            "description": "desc",
            "summary": "sum",
            "extracted_data": {},
            "extraction_confidence": 0.95,
        },
    )
    cluster_records(session, [record_a, record_b])
    first_pass = session.execute(select(SourceComparison)).scalars().all()
    cluster_records(session, [record_a, record_b])
    second_pass = session.execute(select(SourceComparison)).scalars().all()
    session.commit()

    assert len(first_pass) == len(second_pass)
    assert {comparison.field_name for comparison in second_pass} == {"title", "broker"}


def test_make_cluster_key_normalizes_trailing_slash_urls():
    with_slash = make_cluster_key({"source_url": "https://example.com/jobs/1/"})
    without_slash = make_cluster_key({"source_url": "https://example.com/jobs/1"})
    assert with_slash == without_slash


def test_create_digest_item_prevents_second_send_after_status_change():
    session = _session()
    cluster = create_or_update_cluster(
        session=session,
        cluster_key="cluster-a",
        title="Assignment",
        customer="Kynd",
        confidence=0.8,
        review_status=ReviewStatus.NEEDS_REVIEW,
    )
    first = create_digest_item(
        session=session,
        cluster=cluster,
        status=ReviewStatus.NEEDS_REVIEW,
        payload={"cluster_id": cluster.id, "review_status": ReviewStatus.NEEDS_REVIEW.value},
    )
    mark_digest_sent(session, first, slack_ts="123.45")
    session.commit()

    second = create_digest_item(
        session=session,
        cluster=cluster,
        status=ReviewStatus.AUTO_ACCEPTED,
        payload={"cluster_id": cluster.id, "review_status": ReviewStatus.AUTO_ACCEPTED.value},
    )
    session.commit()

    digest_items = session.execute(select(DigestItem)).scalars().all()
    assert second.id == first.id
    assert second.sent_at is not None
    assert len(digest_items) == 1


def test_cluster_to_payload_uses_primary_source_deadline():
    session = _session()
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="scraper",
            source_name="mercell",
            external_id="id-deadline",
            raw_body="raw-deadline",
        ),
    )
    primary = create_extracted_record(
        session,
        {
            "raw_source_item_id": raw.id,
            "title": "Assignment",
            "customer": "Kynd",
            "broker": "mercell",
            "source_url": "https://example.com/a",
            "deadline": "2026-07-01",
            "description": "desc",
            "summary": "sum",
            "extracted_data": {},
            "extraction_confidence": 0.9,
        },
    )
    secondary = create_extracted_record(
        session,
        {
            "raw_source_item_id": raw.id,
            "title": "Assignment",
            "customer": "Kynd",
            "broker": "email",
            "source_url": "https://example.com/a",
            "deadline": "2026-08-01",
            "description": "desc",
            "summary": "sum",
            "extracted_data": {},
            "extraction_confidence": 0.8,
        },
    )
    cluster = create_or_update_cluster(
        session=session,
        cluster_key="cluster-deadline",
        title="Assignment",
        customer="Kynd",
        confidence=0.9,
        review_status=ReviewStatus.AUTO_ACCEPTED,
    )
    attach_cluster_source(session, cluster, secondary, confidence=0.8, rationale="email")
    attach_cluster_source(session, cluster, primary, confidence=0.9, rationale="broker")
    cluster.primary_source_record_id = primary.id
    session.commit()

    payload = cluster_to_payload(cluster)
    assert payload.deadline == "2026-07-01"


def test_raw_source_upsert_reuses_external_id_when_body_changes():
    session = _session()
    first = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="email",
            source_name="oppdrag@kynd.no",
            external_id="<message-1@example.com>",
            raw_body="original-body",
        ),
    )
    first_hash = first.content_hash
    second = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="email",
            source_name="oppdrag@kynd.no",
            external_id="<message-1@example.com>",
            raw_body="updated-body",
        ),
    )
    session.commit()

    all_rows = session.execute(select(RawSourceItem)).scalars().all()
    assert second.id == first.id
    assert len(all_rows) == 1
    assert second.raw_body == "updated-body"
    assert second.content_hash != first_hash


def test_orchestrator_reextracts_when_raw_body_changes(monkeypatch):
    from job_scraper.kois.orchestrator import run_kois_pipeline

    session = _session()
    monkeypatch.setattr(
        "job_scraper.kois.orchestrator.fetch_imap_items",
        lambda settings: [],
    )
    monkeypatch.setattr(
        "job_scraper.kois.orchestrator.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "gemini_api_key": None,
                "run_live_slack": False,
                "slack_channel": "job-posting",
            },
        )(),
    )

    first_job = Job(
        job_overview=JobOverview(
            title="Data Engineer",
            company="Kynd",
            delivery_date="2026-06-30",
            job_uri="https://example.com/jobs/1",
        ),
        description="First description",
        platform="Mercell",
    )
    second_job = Job(
        job_overview=JobOverview(
            title="Data Engineer",
            company="Kynd",
            delivery_date="2026-07-15",
            job_uri="https://example.com/jobs/1",
        ),
        description="Updated description",
        platform="Mercell",
    )

    run_kois_pipeline(session=session, scraped_jobs=[first_job])
    run_kois_pipeline(session=session, scraped_jobs=[second_job])

    raw_rows = session.execute(select(RawSourceItem)).scalars().all()
    extracted_rows = session.execute(select(ExtractedRecord)).scalars().all()

    assert len(raw_rows) == 1
    assert len(extracted_rows) == 2
    latest_record = extracted_rows[-1]
    assert latest_record.description == "Updated description"
    assert latest_record.deadline == "2026-07-15"


