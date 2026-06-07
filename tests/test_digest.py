from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from job_scraper.kois.config import KOISSettings
from job_scraper.kois.digest import send_digest_items
from job_scraper.kois.repository import (
    attach_cluster_source,
    create_digest_item,
    create_extracted_record,
    create_or_update_cluster,
    mark_digest_sent,
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

    class SuccessfulSlack(SlackPoster):
        def post_digest(self, payload, channel="job-posting"):
            return {"ts": "123.45"}

    slack = SuccessfulSlack(optional=True)
    first = send_digest_items(
        session=session,
        clusters=[cluster],
        slack=slack,
        live_posting=True,
        channel="job-posting",
    )
    session.commit()
    second = send_digest_items(
        session=session,
        clusters=[cluster],
        slack=slack,
        live_posting=True,
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


def test_digest_drops_unsent_items_when_relevance_falls_below_threshold():
    session = _session()
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="scraper",
            source_name="mercell",
            external_id="id-relevance",
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
            "source_url": "https://example.com/relevance",
            "deadline": "2026-06-30",
            "description": "desc",
            "summary": "sum",
            "extracted_data": {},
            "extraction_confidence": 0.95,
        },
    )
    cluster = create_or_update_cluster(
        session=session,
        cluster_key="https://example.com/relevance",
        title="Assignment",
        customer="Kynd",
        confidence=0.95,
        review_status=ReviewStatus.AUTO_ACCEPTED,
    )
    attach_cluster_source(session, cluster, record, 0.95, "url")
    cluster.primary_source_record_id = record.id
    cluster.relevance_score = 0.2
    create_digest_item(
        session=session,
        cluster=cluster,
        status=cluster.review_status,
        payload={"cluster_id": cluster.id},
    )
    session.commit()

    sent = send_digest_items(
        session=session,
        clusters=[cluster],
        slack=SlackPoster(optional=True),
        live_posting=False,
        channel="job-posting",
        settings=KOISSettings(digest_min_relevance_score=0.8),
    )
    session.commit()

    assert sent == []
    assert len(cluster.digest_items) == 0


def test_digest_cadence_leaves_unsent_for_later_delivery():
    session = _session()
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="scraper",
            source_name="mercell",
            external_id="id-cadence",
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
            "source_url": "https://example.com/cadence",
            "deadline": "2026-06-30",
            "description": "desc",
            "summary": "sum",
            "extracted_data": {},
            "extraction_confidence": 0.95,
        },
    )
    previous_cluster = create_or_update_cluster(
        session=session,
        cluster_key="https://example.com/previous",
        title="Previous",
        customer="Kynd",
        confidence=0.95,
        review_status=ReviewStatus.AUTO_ACCEPTED,
    )
    previous = create_digest_item(
        session=session,
        cluster=previous_cluster,
        status=ReviewStatus.AUTO_ACCEPTED,
        payload={"cluster_id": previous_cluster.id},
    )
    mark_digest_sent(session, previous, slack_ts="123.45")
    session.flush()

    cluster = create_or_update_cluster(
        session=session,
        cluster_key="https://example.com/cadence",
        title="Assignment",
        customer="Kynd",
        confidence=0.95,
        review_status=ReviewStatus.AUTO_ACCEPTED,
    )
    attach_cluster_source(session, cluster, record, 0.95, "url")
    cluster.primary_source_record_id = record.id
    cluster.relevance_score = 0.9
    session.commit()

    sent = send_digest_items(
        session=session,
        clusters=[cluster],
        slack=SlackPoster(optional=True),
        live_posting=False,
        channel="job-posting",
        settings=KOISSettings(digest_cadence_minutes=120),
    )
    session.commit()

    assert sent == []
    assert len(cluster.digest_items) == 1
    assert cluster.digest_items[0].sent_at is None


def test_digest_cadence_ignores_unsent_rows_for_latest_sent_lookup(monkeypatch):
    session = _session()
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="scraper",
            source_name="mercell",
            external_id="id-cadence-null-order",
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
            "source_url": "https://example.com/cadence-null-order",
            "deadline": "2026-06-30",
            "description": "desc",
            "summary": "sum",
            "extracted_data": {},
            "extraction_confidence": 0.95,
        },
    )
    sent_cluster = create_or_update_cluster(
        session=session,
        cluster_key="https://example.com/sent",
        title="Sent",
        customer="Kynd",
        confidence=0.95,
        review_status=ReviewStatus.AUTO_ACCEPTED,
    )
    sent_item = create_digest_item(
        session=session,
        cluster=sent_cluster,
        status=ReviewStatus.AUTO_ACCEPTED,
        payload={"cluster_id": sent_cluster.id},
    )
    mark_digest_sent(session, sent_item, slack_ts="123.45")

    unsent_cluster = create_or_update_cluster(
        session=session,
        cluster_key="https://example.com/unsent",
        title="Unsent",
        customer="Kynd",
        confidence=0.95,
        review_status=ReviewStatus.AUTO_ACCEPTED,
    )
    create_digest_item(
        session=session,
        cluster=unsent_cluster,
        status=ReviewStatus.AUTO_ACCEPTED,
        payload={"cluster_id": unsent_cluster.id},
    )

    candidate_cluster = create_or_update_cluster(
        session=session,
        cluster_key="https://example.com/candidate",
        title="Candidate",
        customer="Kynd",
        confidence=0.95,
        review_status=ReviewStatus.AUTO_ACCEPTED,
    )
    attach_cluster_source(session, candidate_cluster, record, 0.95, "url")
    candidate_cluster.primary_source_record_id = record.id
    candidate_cluster.relevance_score = 0.9
    session.commit()

    original_execute = session.execute

    def _execute_with_postgres_nulls_first(statement, *args, **kwargs):
        if "SELECT digest_items.sent_at" in str(statement):
            assert "sent_at IS NOT NULL" in str(statement)
        return original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", _execute_with_postgres_nulls_first)

    sent = send_digest_items(
        session=session,
        clusters=[candidate_cluster],
        slack=SlackPoster(optional=True),
        live_posting=False,
        channel="job-posting",
        settings=KOISSettings(digest_cadence_minutes=120),
    )
    session.commit()

    assert sent == []
    assert candidate_cluster.digest_items[0].sent_at is None


def test_dry_run_does_not_block_later_live_send_with_cadence():
    session = _session()
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="scraper",
            source_name="mercell",
            external_id="id-dry-run-cadence",
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
            "source_url": "https://example.com/dry-run-cadence",
            "deadline": "2026-06-30",
            "description": "desc",
            "summary": "sum",
            "extracted_data": {},
            "extraction_confidence": 0.95,
        },
    )
    cluster = create_or_update_cluster(
        session=session,
        cluster_key="https://example.com/dry-run-cadence",
        title="Assignment",
        customer="Kynd",
        confidence=0.95,
        review_status=ReviewStatus.AUTO_ACCEPTED,
    )
    attach_cluster_source(session, cluster, record, 0.95, "url")
    cluster.primary_source_record_id = record.id
    cluster.relevance_score = 0.9
    session.commit()

    dry_run = send_digest_items(
        session=session,
        clusters=[cluster],
        slack=SlackPoster(optional=True),
        live_posting=False,
        channel="job-posting",
        settings=KOISSettings(digest_cadence_minutes=120),
    )
    session.commit()

    assert len(dry_run) == 1
    assert cluster.digest_items[0].sent_at is None

    class SuccessfulSlack(SlackPoster):
        def post_digest(self, payload, channel="job-posting"):
            return {"ts": "456.78"}

    live_run = send_digest_items(
        session=session,
        clusters=[cluster],
        slack=SuccessfulSlack(optional=True),
        live_posting=True,
        channel="job-posting",
        settings=KOISSettings(digest_cadence_minutes=120),
    )
    session.commit()

    assert len(live_run) == 1
    assert cluster.digest_items[0].sent_at is not None
