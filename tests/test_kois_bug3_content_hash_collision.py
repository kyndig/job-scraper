from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from job_scraper.kois.domain import RawIngestionItem
from job_scraper.kois.repository import upsert_raw_source_item
from job_scraper.kois.schema import Base, RawSourceItem


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(bind=engine, future=True)


def test_raw_source_upsert_avoids_hash_collision_when_external_content_changes():
    session = _session()
    existing_by_external = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="email",
            source_name="oppdrag@kynd.no",
            external_id="<message-1@example.com>",
            raw_body="body-one",
        ),
    )
    existing_by_hash = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="email",
            source_name="oppdrag@kynd.no",
            external_id="<message-2@example.com>",
            raw_body="body-two",
        ),
    )
    collided = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="email",
            source_name="oppdrag@kynd.no",
            external_id="<message-1@example.com>",
            raw_body="body-two",
            metadata={"subject": "latest"},
        ),
    )
    session.commit()

    all_rows = session.execute(select(RawSourceItem)).scalars().all()
    assert collided.id == existing_by_hash.id
    assert existing_by_external.id != existing_by_hash.id
    assert len(all_rows) == 2
