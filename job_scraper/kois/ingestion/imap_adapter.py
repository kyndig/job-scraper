from __future__ import annotations

import email
import imaplib
import logging
import re
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from sqlalchemy.orm import Session

from job_scraper.kois.config import ImapAccount, KOISSettings
from job_scraper.kois.domain import RawIngestionItem
from job_scraper.kois.repository import get_ingest_cursor_uid, upsert_ingest_cursor

logger = logging.getLogger(__name__)

_HTML_WHITESPACE = re.compile(r"\s+")


class ImapIngestError(RuntimeError):
    """Raised when a configured IMAP account cannot be fetched."""


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._chunks.append(href)

    def handle_data(self, data: str) -> None:
        if data:
            self._chunks.append(data)

    def text(self) -> str:
        return _HTML_WHITESPACE.sub(" ", " ".join(self._chunks)).strip()


def _html_to_text(value: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(value)
    extractor.close()
    return extractor.text()


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for payload, encoding in parts:
        if isinstance(payload, bytes):
            decoded.append(payload.decode(encoding or "utf-8", errors="ignore"))
        else:
            decoded.append(payload)
    return "".join(decoded)


def _decode_part(part: email.message.Message) -> str:
    content = part.get_payload(decode=True) or b""
    return content.decode(part.get_content_charset() or "utf-8", errors="ignore")


def _message_body(message: email.message.Message) -> str:
    if message.is_multipart():
        plain_chunks: list[str] = []
        html_chunks: list[str] = []
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                plain_chunks.append(_decode_part(part))
            elif content_type == "text/html":
                html_chunks.append(_decode_part(part))
        if plain_chunks:
            return "\n".join(plain_chunks)
        if html_chunks:
            return _html_to_text("\n".join(html_chunks))
        return ""

    content = _decode_part(message)
    if message.get_content_type() == "text/html":
        return _html_to_text(content)
    return content


def _extract_rfc822_bytes(payload) -> bytes | None:
    if not payload:
        return None

    for part in payload:
        if isinstance(part, tuple) and len(part) >= 2:
            body = part[1]
            if isinstance(body, bytes):
                return body
        elif isinstance(part, bytes):
            return part
    return None


def _message_received_at(message: email.message.Message) -> datetime:
    raw_date = message.get("Date")
    if raw_date:
        try:
            parsed = parsedate_to_datetime(raw_date)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            pass
    return datetime.now(timezone.utc)


def _since_uid_for_account(
    session: Session | None, account: ImapAccount
) -> int:
    if session is None:
        return account.since_uid
    last_uid = get_ingest_cursor_uid(
        session,
        source_type="email",
        source_name=account.source_name,
        mailbox=account.mailbox,
    )
    if last_uid is None:
        return account.since_uid
    return last_uid + 1


def _imap_status_ok(status) -> bool:
    if isinstance(status, bytes):
        status = status.decode("utf-8", errors="ignore")
    return status == "OK"


def fetch_account_items(
    account: ImapAccount, session: Session | None = None
) -> list[RawIngestionItem]:
    since_uid = _since_uid_for_account(session, account)
    fetched_uids: list[int] = []
    raw_items: list[RawIngestionItem] = []
    connection = None
    try:
        connection = imaplib.IMAP4_SSL(account.host, account.port)
        login_status, _ = connection.login(account.username, account.password)
        if not _imap_status_ok(login_status):
            raise ImapIngestError(
                f"IMAP login failed for {account.source_name} ({account.username})"
            )
        select_status, _ = connection.select(account.mailbox)
        if not _imap_status_ok(select_status):
            raise ImapIngestError(
                f"IMAP select failed for {account.source_name} mailbox {account.mailbox}"
            )
        status, response = connection.uid("SEARCH", None, f"UID {since_uid}:*")
        if not _imap_status_ok(status) or not response or not response[0]:
            return raw_items

        for uid in response[0].split():
            fetch_status, payload = connection.uid("FETCH", uid, "(RFC822)")
            if not _imap_status_ok(fetch_status) or not payload:
                continue

            raw_email = _extract_rfc822_bytes(payload)
            if raw_email is None:
                continue
            message = email.message_from_bytes(raw_email)
            uid_text = uid.decode("utf-8")
            message_id = message.get("Message-ID", uid_text)
            body = _message_body(message)
            subject = _decode_header(message.get("Subject"))
            metadata = {
                "uid": uid_text,
                "subject": subject,
                "from": _decode_header(message.get("From")),
                "to": _decode_header(message.get("To")),
                "cc": _decode_header(message.get("Cc")),
                "date": _decode_header(message.get("Date")),
                "mailbox": account.mailbox,
                "message_id": message_id,
            }
            raw_items.append(
                RawIngestionItem(
                    source_type="email",
                    source_name=account.source_name,
                    external_id=message_id,
                    raw_body=body,
                    metadata=metadata,
                    received_at=_message_received_at(message),
                )
            )
            fetched_uids.append(int(uid_text))
    except ImapIngestError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ImapIngestError(
            f"IMAP fetch failed for {account.source_name}: {exc}"
        ) from exc
    finally:
        if connection is not None:
            try:
                connection.logout()
            except Exception:  # noqa: BLE001
                logger.debug("IMAP logout failed for %s", account.source_name)

    if session is not None and fetched_uids:
        upsert_ingest_cursor(
            session,
            source_type="email",
            source_name=account.source_name,
            mailbox=account.mailbox,
            last_uid=max(fetched_uids),
        )
    return raw_items


def fetch_imap_items(
    settings: KOISSettings, session: Session | None = None
) -> list[RawIngestionItem]:
    accounts = settings.imap_accounts
    if not accounts:
        logger.info("IMAP disabled: no accounts configured")
        return []

    raw_items: list[RawIngestionItem] = []
    for account in accounts:
        try:
            raw_items.extend(fetch_account_items(account, session=session))
        except ImapIngestError:
            logger.exception(
                "IMAP ingest failed for %s; continuing with remaining sources",
                account.source_name,
            )
    return raw_items
