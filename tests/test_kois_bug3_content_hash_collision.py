from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from job_scraper.kois.domain import RawIngestionItem
from job_scraper.kois.repository import upsert_raw_source_item
from job_scraper.kois.schema import Base, RawSourceItem


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(bind=engine, future=True)


def test_raw_source_upsert_updates_external_id_row_when_body_matches_existing_hash():
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
            metadata={"subject": "message-two"},
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
    session.refresh(existing_by_hash)

    all_rows = session.execute(select(RawSourceItem)).scalars().all()
    assert collided.id == existing_by_external.id
    assert collided.external_id == "<message-1@example.com>"
    assert collided.raw_body == "body-two"
    assert collided.metadata_json == {"subject": "latest"}
    assert existing_by_hash.raw_body == "body-two"
    assert existing_by_hash.metadata_json == {"subject": "message-two"}
    assert len(all_rows) == 2
