from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from job_scraper.kois.clustering import cluster_records
from job_scraper.kois.domain import RawIngestionItem
from job_scraper.kois.repository import create_extracted_record, upsert_raw_source_item
from job_scraper.kois.schema import Base, OpportunityCluster


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(bind=engine, future=True)


def test_primary_source_prefers_scraper_over_email_when_broker_label_is_not_literal():
    session = _session()
    raw_email = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="email",
            source_name="oppdrag@kynd.no",
            external_id="mail-1",
            raw_body="email-content",
        ),
    )
    raw_scraper = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="scraper",
            source_name="mercell",
            external_id="scraper-1",
            raw_body="scraper-content",
        ),
    )
    email_record = create_extracted_record(
        session,
        {
            "raw_source_item_id": raw_email.id,
            "title": "Data Engineer",
            "customer": "Kynd",
            "broker": "sender@example.com",
            "source_url": "https://example.com/a",
            "deadline": "2026-06-30",
            "description": "desc",
            "summary": "sum",
            "extracted_data": {"source_type": "email"},
            "extraction_confidence": 0.8,
        },
    )
    scraper_record = create_extracted_record(
        session,
        {
            "raw_source_item_id": raw_scraper.id,
            "title": "Data Engineer",
            "customer": "Kynd",
            "broker": "Mercell",
            "source_url": "https://example.com/a",
            "deadline": "2026-06-30",
            "description": "desc",
            "summary": "sum",
            "extracted_data": {"source_type": "scraper", "platform": "Mercell"},
            "extraction_confidence": 0.9,
        },
    )

    cluster_records(session, [email_record, scraper_record])
    session.commit()

    cluster = session.execute(select(OpportunityCluster)).scalar_one()
    assert cluster.primary_source_record_id == scraper_record.id
