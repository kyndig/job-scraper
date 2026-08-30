from datetime import datetime, timezone
import logging

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from job_scraper.kois.config import ImapAccount, KOISSettings
from job_scraper.kois.ingestion.imap_adapter import (
    ImapIngestError,
    fetch_account_items,
    fetch_imap_items,
)
from job_scraper.kois.schema import Base, IngestCursor


class FakeImapConnection:
    def __init__(self, message: bytes | None = None, uids: bytes = b"1"):
        self.logged_in = False
        self.selected = None
        self.searches: list[tuple] = []
        self._message = message or (
            b"From: sender@example.com\r\n"
            b"To: oppdrag@kynd.no\r\n"
            b"Subject: Oppdrag: Data Engineer\r\n"
            b"Message-ID: <msg1@example.com>\r\n"
            b"Date: Fri, 05 Jun 2026 12:00:00 +0000\r\n"
            b"\r\n"
            b"Frist: 2026-06-30\r\n"
            b"Se mer: https://example.com/job/1\r\n"
        )
        self._uids = uids

    def login(self, _username, _password):
        self.logged_in = True
        return "OK", [b"Logged in"]

    def select(self, mailbox):
        self.selected = mailbox
        return "OK", [b"1"]

    def uid(self, command, *_args):
        if command == "SEARCH":
            self.searches.append(_args)
            return "OK", [self._uids]
        if command == "FETCH":
            return "OK", [(b"1 (RFC822 {200}", self._message)]
        return "NO", []

    def logout(self):
        return "BYE", [b"logout"]


class FailingLoginConnection(FakeImapConnection):
    def login(self, _username, _password):
        raise Exception("AUTHENTICATIONFAILED")


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(bind=engine, future=True)


def test_fetch_imap_items_maps_email_to_raw_item(monkeypatch):
    monkeypatch.setattr(
        "job_scraper.kois.ingestion.imap_adapter.imaplib.IMAP4_SSL",
        lambda _host, _port: FakeImapConnection(),
    )
    settings = KOISSettings(
        imap_host="imap.example.com",
        imap_username="user",
        imap_password="pass",
        imap_source_name="oppdrag@kynd.no",
    )

    items = fetch_imap_items(settings)
    assert len(items) == 1
    assert items[0].source_type == "email"
    assert items[0].external_id == "<msg1@example.com>"
    assert "https://example.com/job/1" in items[0].raw_body
    assert items[0].received_at == datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)


def test_fetch_imap_items_disabled_without_accounts(caplog):
    caplog.set_level(logging.INFO)
    settings = KOISSettings(_env_file=None)
    items = fetch_imap_items(settings)
    assert items == []
    assert "IMAP disabled" in caplog.text


def test_html_only_email_falls_back_to_text(monkeypatch):
    html_message = (
        b"From: sender@example.com\r\n"
        b"To: oppdrag@kynd.no\r\n"
        b"Subject: HTML assignment\r\n"
        b"Message-ID: <html1@example.com>\r\n"
        b"Date: Fri, 05 Jun 2026 12:00:00 +0000\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: text/html; charset="utf-8"\r\n'
        b"\r\n"
        b"<html><body><p>Frist: 2026-06-30</p>"
        b'<p>Se mer: <a href="https://example.com/job/html">lenke</a></p></body></html>\r\n'
    )
    monkeypatch.setattr(
        "job_scraper.kois.ingestion.imap_adapter.imaplib.IMAP4_SSL",
        lambda _host, _port: FakeImapConnection(message=html_message),
    )
    settings = KOISSettings(
        imap_host="imap.example.com",
        imap_username="user",
        imap_password="pass",
    )
    items = fetch_imap_items(settings)
    assert len(items) == 1
    assert "Frist: 2026-06-30" in items[0].raw_body
    assert "https://example.com/job/html" in items[0].raw_body
    assert "<p>" not in items[0].raw_body


def test_multi_account_imap_fetches_each_mailbox(monkeypatch):
    connections: dict[str, FakeImapConnection] = {}

    def factory(host, _port):
        connection = FakeImapConnection(
            message=(
                b"From: sender@example.com\r\n"
                b"To: " + host.encode() + b"\r\n"
                b"Subject: Job\r\n"
                b"Message-ID: <" + host.encode() + b"@example.com>\r\n"
                b"Date: Fri, 05 Jun 2026 12:00:00 +0000\r\n"
                b"\r\n"
                b"Body for " + host.encode() + b"\r\n"
            )
        )
        connections[host] = connection
        return connection

    monkeypatch.setattr(
        "job_scraper.kois.ingestion.imap_adapter.imaplib.IMAP4_SSL",
        factory,
    )
    settings = KOISSettings(
        imap_accounts_json=(
            '[{"host":"imap-a.example.com","username":"a@kynd.no","password":"p1",'
            '"source_name":"a@kynd.no"},'
            '{"host":"imap-b.example.com","username":"b@kynd.no","password":"p2",'
            '"source_name":"b@kynd.no","mailbox":"Assignments"}]'
        )
    )
    items = fetch_imap_items(settings)
    assert {item.source_name for item in items} == {"a@kynd.no", "b@kynd.no"}
    assert connections["imap-b.example.com"].selected == "Assignments"


def test_uid_cursor_advances_after_successful_fetch(monkeypatch):
    connection = FakeImapConnection(uids=b"5 6")
    monkeypatch.setattr(
        "job_scraper.kois.ingestion.imap_adapter.imaplib.IMAP4_SSL",
        lambda _host, _port: connection,
    )
    session = _session()
    settings = KOISSettings(
        imap_host="imap.example.com",
        imap_username="user",
        imap_password="pass",
        imap_source_name="oppdrag@kynd.no",
    )
    items = fetch_imap_items(settings, session)
    assert len(items) == 2
    cursor = session.execute(select(IngestCursor)).scalar_one()
    assert cursor.last_uid == 6
    assert connection.searches[0][-1] == "UID 1:*"

    second = FakeImapConnection(uids=b"7")
    monkeypatch.setattr(
        "job_scraper.kois.ingestion.imap_adapter.imaplib.IMAP4_SSL",
        lambda _host, _port: second,
    )
    fetch_imap_items(settings, session)
    assert second.searches[0][-1] == "UID 7:*"
    assert session.execute(select(IngestCursor)).scalar_one().last_uid == 7


def test_configured_login_failure_raises_loudly(monkeypatch):
    monkeypatch.setattr(
        "job_scraper.kois.ingestion.imap_adapter.imaplib.IMAP4_SSL",
        lambda _host, _port: FailingLoginConnection(),
    )
    account = ImapAccount(
        host="imap.example.com",
        username="user",
        password="pass",
        source_name="oppdrag@kynd.no",
    )
    try:
        fetch_account_items(account)
        raised = False
    except ImapIngestError as exc:
        raised = True
        assert "oppdrag@kynd.no" in str(exc)
    assert raised


def test_one_account_failure_does_not_abort_others(monkeypatch, caplog):
    def factory(host, _port):
        if host == "bad.example.com":
            return FailingLoginConnection()
        return FakeImapConnection()

    monkeypatch.setattr(
        "job_scraper.kois.ingestion.imap_adapter.imaplib.IMAP4_SSL",
        factory,
    )
    settings = KOISSettings(
        imap_accounts_json=(
            '[{"host":"bad.example.com","username":"bad@kynd.no","password":"x",'
            '"source_name":"bad@kynd.no"},'
            '{"host":"good.example.com","username":"good@kynd.no","password":"y",'
            '"source_name":"good@kynd.no"}]'
        )
    )
    items = fetch_imap_items(settings)
    assert len(items) == 1
    assert items[0].source_name == "good@kynd.no"
    assert "IMAP ingest failed for bad@kynd.no" in caplog.text
