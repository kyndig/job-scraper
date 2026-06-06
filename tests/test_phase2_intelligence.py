from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from job_scraper.kois.agreement_signals import build_agreement_signal_payload
from job_scraper.kois.analytics import phase2_summary
from job_scraper.kois.db import Base
from job_scraper.kois.extraction import RecordExtractor
from job_scraper.kois.gaps import discover_missing_agreement_gaps, set_gap_status
from job_scraper.kois.ingestion.procurement_adapter import fetch_procurement_items
from job_scraper.kois.config import KOISSettings
from job_scraper.kois.repository import (
    create_extracted_record,
    list_agreement_gaps,
    upsert_agreement_gap,
    upsert_agreement_signal,
    upsert_raw_source_item,
)
from job_scraper.kois import review_api
from job_scraper.kois.schema import GapStatus
from job_scraper.kois.clustering import cluster_records
from job_scraper.kois.domain import RawIngestionItem, SourceKind, infer_source_kind


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(bind=engine, future=True)


def test_procurement_adapter_reads_embedded_feeds():
    settings = KOISSettings(
        doffin_feed_json='[{"id":"n-1","title":"DPS Cloud","buyer":"Oslo","agreement_type":"dps"}]',
        procurement_feed_json_by_source={
            "anskaffelser": '[{"id":"n-2","title":"Frame Python","buyer":"Bergen","agreement_type":"frame"}]'
        },
    )
    items = fetch_procurement_items(settings)
    assert len(items) == 2
    assert {item.source_name for item in items} == {"doffin", "anskaffelser"}
    assert all(item.source_type == "procurement" for item in items)


def test_source_kind_priority_prefers_public_tender():
    session = _session()
    raw_public = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="procurement",
            source_name="doffin",
            external_id="d-1",
            raw_body='{"id":"d-1"}',
            metadata={
                "notice_payload": {
                    "id": "d-1",
                    "title": "Senior Python",
                    "buyer": "Kynd",
                    "url": "https://example.com/opportunity",
                }
            },
        ),
    )
    raw_broker = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="scraper",
            source_name="mercell",
            external_id="m-1",
            raw_body='{"id":"m-1"}',
        ),
    )
    public_record = create_extracted_record(
        session,
        {
            "raw_source_item_id": raw_public.id,
            "title": "Senior Python",
            "customer": "Kynd",
            "broker": "Doffin",
            "source_url": "https://example.com/opportunity",
            "deadline": "2026-07-01",
            "description": "public notice",
            "summary": None,
            "extraction_confidence": 0.9,
            "extracted_data": {"source_kind": "public_tender"},
        },
    )
    broker_record = create_extracted_record(
        session,
        {
            "raw_source_item_id": raw_broker.id,
            "title": "Senior Python",
            "customer": "Kynd",
            "broker": "Mercell",
            "source_url": "https://example.com/opportunity",
            "deadline": "2026-07-01",
            "description": "broker summary",
            "summary": None,
            "extraction_confidence": 0.9,
            "extracted_data": {"source_kind": "broker"},
        },
    )
    clusters = cluster_records(session, [broker_record, public_record])
    session.commit()
    assert clusters[-1].primary_source_record_id == public_record.id


def test_agreement_gap_discovery_and_api():
    session = _session()
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="procurement",
            source_name="doffin",
            external_id="notice-1",
            raw_body='{"id":"notice-1"}',
            metadata={"notice_payload": {"title": "DPS backend", "buyer": "Oslo kommune"}},
        ),
    )
    record = RecordExtractor().extract(raw)
    extracted = create_extracted_record(session, record)
    cluster_records(session, [extracted, extracted])
    session.commit()

    discover_missing_agreement_gaps(session, min_cluster_hits=1)
    session.commit()
    gaps = list_agreement_gaps(session)
    assert len(gaps) == 1
    assert gaps[0].status == GapStatus.OPEN

    upsert_agreement_signal(
        session,
        {
            "raw_source_item_id": raw.id,
            "source_name": "doffin",
            "external_id": "notice-1",
            "title": "DPS backend",
            "buyer_name": "Oslo kommune",
            "agreement_type": "dps",
            "category": "it",
            "status": "open",
            "source_url": "https://example.com/n/1",
            "published_at": None,
            "deadline": None,
            "signal_confidence": 0.8,
            "metadata_json": {},
        },
    )
    session.commit()

    discover_missing_agreement_gaps(session, min_cluster_hits=1)
    session.commit()

    summary = review_api.analytics_summary(session)
    assert "coverage" in summary
    assert summary["coverage"]["open_gap_count"] == 0

    gaps_response = review_api.agreement_gaps(status=None, session=session)
    assert len(gaps_response) >= 1
    assert gaps_response[0]["status"] == GapStatus.IGNORED.value

    patch_response = review_api.update_agreement_gap_status(
        gap_id=gaps[0].id,
        update=review_api.GapStatusUpdate(
            status=GapStatus.WATCH_ONLY,
            actor="tester",
            note="monitor",
        ),
        session=session,
    )
    assert patch_response["status"] == "watch_only"


def test_phase2_summary_contract():
    session = _session()
    summary = phase2_summary(session)
    assert set(summary) == {"buyer_trends", "broker_patterns", "source_quality", "coverage"}


def test_gap_upsert_preserves_acknowledged_status():
    session = _session()
    created = upsert_agreement_gap(
        session,
        {
            "gap_key": "buyer:oslo",
            "buyer_name": "Oslo kommune",
            "status": GapStatus.OPEN,
            "confidence": 0.6,
            "rationale": "initial",
            "evidence_json": {"cluster_count": 2},
        },
    )
    created.status = GapStatus.ACKNOWLEDGED
    session.flush()

    updated = upsert_agreement_gap(
        session,
        {
            "gap_key": "buyer:oslo",
            "buyer_name": "Oslo kommune",
            "status": GapStatus.OPEN,
            "confidence": 0.8,
            "rationale": "updated",
            "evidence_json": {"cluster_count": 3},
        },
    )
    assert updated.status == GapStatus.ACKNOWLEDGED


def test_agreement_signal_detection_ignores_non_procurement_framework_mentions():
    session = _session()
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="scraper",
            source_name="broker-feed",
            external_id="s-1",
            raw_body="framework-heavy assignment",
            metadata={},
        ),
    )
    record = create_extracted_record(
        session,
        {
            "raw_source_item_id": raw.id,
            "title": "Senior engineer assignment",
            "customer": "City",
            "broker": "Broker",
            "source_url": "https://example.com/s-1",
            "deadline": None,
            "description": "Requires deep experience in framework migration work.",
            "summary": None,
            "extraction_confidence": 0.7,
            "extracted_data": {"source_kind": "broker"},
        },
    )

    payload = build_agreement_signal_payload(raw_item=raw, record=record)
    assert payload is None


def test_infer_source_kind_does_not_promote_generic_tender_scrapers():
    source_kind = infer_source_kind(
        source_type="scraper",
        source_name="tender-hub-broker",
        metadata={"platform": "Talent Tender Board"},
    )
    assert source_kind == SourceKind.BROKER


def test_agreement_signal_detects_compact_agreement_type_values():
    session = _session()
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="procurement",
            source_name="feed",
            external_id="compact-1",
            raw_body='{"id":"compact-1"}',
            metadata={
                "notice_payload": {
                    "title": "Cloud operations procurement",
                    "buyer": "Oslo kommune",
                    "agreement_type": "frame",
                }
            },
        ),
    )
    record = create_extracted_record(
        session,
        {
            "raw_source_item_id": raw.id,
            "title": "Cloud operations procurement",
            "customer": "Oslo kommune",
            "broker": "feed",
            "source_url": "https://example.com/compact-1",
            "deadline": None,
            "description": "procurement notice",
            "summary": None,
            "extraction_confidence": 0.8,
            "extracted_data": {"agreement_type": "frame", "source_kind": "public_tender"},
        },
    )

    payload = build_agreement_signal_payload(raw_item=raw, record=record)
    assert payload is not None
    assert payload["agreement_type"] == "frame"


def test_set_gap_status_preserves_existing_note_when_note_is_omitted():
    session = _session()
    gap = upsert_agreement_gap(
        session,
        {
            "gap_key": "buyer:trondheim",
            "buyer_name": "Trondheim kommune",
            "status": GapStatus.OPEN,
            "confidence": 0.7,
            "rationale": "Repeated demand",
            "evidence_json": {"cluster_count": 2},
        },
    )
    gap.note = "Needs legal validation"
    session.flush()

    updated = set_gap_status(
        session=session,
        gap_id=gap.id,
        status=GapStatus.ACKNOWLEDGED,
        actor="tester",
        note=None,
    )
    assert updated.status == GapStatus.ACKNOWLEDGED
    assert updated.note == "Needs legal validation"
