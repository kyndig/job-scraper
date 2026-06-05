from job_scraper.kois.config import KOISSettings
from job_scraper.kois.ingestion.imap_adapter import fetch_imap_items


class FakeImapConnection:
    def __init__(self):
        self.logged_in = False

    def login(self, _username, _password):
        self.logged_in = True
        return "OK", [b"Logged in"]

    def select(self, _mailbox):
        return "OK", [b"1"]

    def uid(self, command, *_args):
        if command == "SEARCH":
            return "OK", [b"1"]
        if command == "FETCH":
            message = (
                b"From: sender@example.com\r\n"
                b"To: oppdrag@kynd.no\r\n"
                b"Subject: Oppdrag: Data Engineer\r\n"
                b"Message-ID: <msg1@example.com>\r\n"
                b"Date: Fri, 05 Jun 2026 12:00:00 +0000\r\n"
                b"\r\n"
                b"Frist: 2026-06-30\r\n"
                b"Se mer: https://example.com/job/1\r\n"
            )
            return "OK", [(b"1 (RFC822 {200}", message)]
        return "NO", []

    def logout(self):
        return "BYE", [b"logout"]


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
