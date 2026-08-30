from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from job_scraper.kois import review_api
from job_scraper.kois.auth import extract_review_token, review_access_decision
from job_scraper.kois.config import KOISSettings
from job_scraper.kois.domain import RawIngestionItem
from job_scraper.kois.repository import (
    attach_cluster_source,
    create_extracted_record,
    create_or_update_cluster,
    upsert_raw_source_item,
)
from job_scraper.kois.schema import Base, ReviewStatus
from job_scraper.main import parse_args


def _request(path: str = "/ui") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("test", 50000),
            "server": ("test", 80),
        }
    )


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(bind=engine, future=True)


def _make_cluster(session: Session, *, title: str = "Data Engineer"):
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="email",
            source_name="oppdrag@kynd.no",
            external_id="<msg-detail@example.com>",
            raw_body="Frist: 2026-06-30\nSe mer: https://example.com/job/detail",
            metadata={"subject": "Oppdrag: Data Engineer"},
        ),
    )
    record = create_extracted_record(
        session,
        {
            "raw_source_item_id": raw.id,
            "title": title,
            "customer": "Kynd",
            "broker": None,
            "source_url": "https://example.com/job/detail",
            "deadline": "2026-06-30",
            "description": "Need a data engineer",
            "summary": None,
            "extracted_data": {},
            "extraction_confidence": 0.9,
        },
    )
    cluster = create_or_update_cluster(
        session=session,
        cluster_key="https://example.com/job/detail",
        title=title,
        customer="Kynd",
        confidence=0.9,
        review_status=ReviewStatus.NEEDS_REVIEW,
    )
    attach_cluster_source(session, cluster, record, 0.9, "url")
    cluster.primary_source_record_id = record.id
    session.commit()
    return cluster


def test_healthcheck_queries_database():
    session = _session()
    assert review_api.healthcheck(session=session) == {"ok": True, "database": "ok"}


def test_cluster_detail_includes_sources_and_snippet():
    session = _session()
    cluster = _make_cluster(session)
    payload = review_api.get_cluster_detail(cluster_id=cluster.id, session=session)
    assert payload["title"] == "Data Engineer"
    assert payload["sources"][0]["source_name"] == "oppdrag@kynd.no"
    assert "https://example.com/job/detail" in payload["sources"][0]["raw_snippet"]


def test_cluster_detail_missing_returns_404():
    session = _session()
    try:
        review_api.get_cluster_detail(cluster_id=999, session=session)
        raised = False
    except Exception as exc:
        raised = True
        assert getattr(exc, "status_code", None) == 404
    assert raised


def test_ingest_summary_counts_email_sources():
    session = _session()
    _make_cluster(session)
    summary = review_api.ingest_summary_view(session=session)
    assert summary["total"] == 1
    assert summary["by_source"][0]["source_type"] == "email"
    assert summary["by_source"][0]["source_name"] == "oppdrag@kynd.no"
    sources = review_api.ingest_sources(session=session)
    assert sources[0]["subject"] == "Oppdrag: Data Engineer"


def test_review_token_decisions():
    assert review_access_decision("/clusters", None, None) == "allow"
    assert review_access_decision("/health", None, "secret") == "allow"
    assert review_access_decision("/ui", None, "secret") == "login"
    assert review_access_decision("/clusters", None, "secret") == "unauthorized"
    assert (
        review_access_decision("/clusters", "secret", "secret") == "allow"
    )
    assert extract_review_token("Bearer secret", None) == "secret"


def test_email_only_flag_parses():
    assert parse_args(["--email-only"]).email_only is True
    assert parse_args([]).email_only is False


def test_settings_parse_imap_accounts_json():
    settings = KOISSettings(
        imap_accounts_json=(
            '[{"host":"imap.example.com","username":"a@kynd.no","password":"x"}]'
        )
    )
    assert len(settings.imap_accounts) == 1
    assert settings.imap_accounts[0].source_name == "a@kynd.no"


def test_ui_inbox_and_sources_render():
    session = _session()
    cluster = _make_cluster(session)
    inbox = review_api.ui_inbox(request=_request("/ui"), session=session)
    assert inbox.context["summary"]["total"] == 1
    assert inbox.context["clusters"][0]["title"] == "Data Engineer"
    sources = review_api.ui_sources(request=_request("/ui/sources"), session=session)
    assert sources.context["sources"][0]["source_name"] == "oppdrag@kynd.no"
    detail = review_api.ui_cluster_detail(
        request=_request(f"/ui/clusters/{cluster.id}"),
        cluster_id=cluster.id,
        session=session,
    )
    assert detail.context["cluster"]["title"] == "Data Engineer"
    assert detail.context["cluster"]["sources"][0]["raw_snippet"]
