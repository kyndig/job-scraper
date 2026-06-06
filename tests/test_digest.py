from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from job_scraper.kois.digest import send_digest_items
from job_scraper.kois.repository import (
    attach_cluster_source,
    create_extracted_record,
    create_or_update_cluster,
    upsert_raw_source_item,
)
from job_scraper.kois.schema import Base, ReviewStatus
from job_scraper.kois.domain import RawIngestionItem
from job_scraper.slack_poster import SlackPoster


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(bind=engine, future=True)


def test_digest_item_not_resent_when_already_sent():
    session = _session()
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="scraper",
            source_name="mercell",
            external_id="id",
            raw_body="raw-data",
        ),
    )
    record = create_extracted_record(
        session,
        {
            "raw_source_item_id": raw.id,
            "title": "Assignment",
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
    cluster = create_or_update_cluster(
        session=session,
        cluster_key="https://example.com/a",
        title="Assignment",
        customer="Kynd",
        confidence=0.95,
        review_status=ReviewStatus.AUTO_ACCEPTED,
    )
    attach_cluster_source(session, cluster, record, 0.95, "url")
    cluster.primary_source_record_id = record.id
    session.commit()

    slack = SlackPoster(optional=True)
    first = send_digest_items(
        session=session,
        clusters=[cluster],
        slack=slack,
        live_posting=False,
        channel="job-posting",
    )
    session.commit()
    second = send_digest_items(
        session=session,
        clusters=[cluster],
        slack=slack,
        live_posting=False,
        channel="job-posting",
    )
    session.commit()

    assert len(first) == 1
    assert len(second) == 0


def test_digest_not_marked_sent_when_live_post_fails():
    session = _session()
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="scraper",
            source_name="mercell",
            external_id="id",
            raw_body="raw-data",
        ),
    )
    record = create_extracted_record(
        session,
        {
            "raw_source_item_id": raw.id,
            "title": "Assignment",
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
    cluster = create_or_update_cluster(
        session=session,
        cluster_key="https://example.com/a",
        title="Assignment",
        customer="Kynd",
        confidence=0.95,
        review_status=ReviewStatus.AUTO_ACCEPTED,
    )
    attach_cluster_source(session, cluster, record, 0.95, "url")
    cluster.primary_source_record_id = record.id
    session.commit()

    class FailingSlack(SlackPoster):
        def post_digest(self, payload, channel="job-posting"):
            return None

    sent = send_digest_items(
        session=session,
        clusters=[cluster],
        slack=FailingSlack(optional=True),
        live_posting=True,
        channel="job-posting",
    )
    session.commit()

    assert sent == []
    assert cluster.digest_items[0].sent_at is None
