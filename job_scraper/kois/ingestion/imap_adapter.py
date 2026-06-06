from __future__ import annotations

import email
import imaplib
from datetime import datetime, timezone
from email.header import decode_header

from job_scraper.kois.config import KOISSettings
from job_scraper.kois.domain import RawIngestionItem


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


def _message_body(message: email.message.Message) -> str:
    if message.is_multipart():
        chunks = []
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                content = part.get_payload(decode=True) or b""
                chunks.append(content.decode(part.get_content_charset() or "utf-8", errors="ignore"))
        return "\n".join(chunks)

    content = message.get_payload(decode=True) or b""
    return content.decode(message.get_content_charset() or "utf-8", errors="ignore")


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


def fetch_imap_items(settings: KOISSettings) -> list[RawIngestionItem]:
    if not settings.imap_host or not settings.imap_username or not settings.imap_password:
        return []

    raw_items: list[RawIngestionItem] = []
    connection = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    try:
        connection.login(settings.imap_username, settings.imap_password)
        connection.select(settings.imap_mailbox)
        status, response = connection.uid("SEARCH", None, f"UID {settings.imap_since_uid}:*")
        if status != "OK" or not response or not response[0]:
            return raw_items

        for uid in response[0].split():
            fetch_status, payload = connection.uid("FETCH", uid, "(RFC822)")
            if fetch_status != "OK" or not payload:
                continue

            raw_email = _extract_rfc822_bytes(payload)
            if raw_email is None:
                continue
            message = email.message_from_bytes(raw_email)
            message_id = message.get("Message-ID", uid.decode("utf-8"))
            body = _message_body(message)
            subject = _decode_header(message.get("Subject"))
            metadata = {
                "uid": uid.decode("utf-8"),
                "subject": subject,
                "from": _decode_header(message.get("From")),
                "to": _decode_header(message.get("To")),
                "cc": _decode_header(message.get("Cc")),
                "date": _decode_header(message.get("Date")),
                "mailbox": settings.imap_mailbox,
                "message_id": message_id,
            }
            raw_items.append(
                RawIngestionItem(
                    source_type="email",
                    source_name=settings.imap_source_name,
                    external_id=message_id,
                    raw_body=body,
                    metadata=metadata,
                    received_at=datetime.now(timezone.utc),
                )
            )
    finally:
        connection.logout()

    return raw_items
