from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from job_scraper.kois.utils import normalize_text


@dataclass
class RawIngestionItem:
    source_type: str
    source_name: str
    external_id: str
    raw_body: str
    metadata: dict = field(default_factory=dict)
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SourceKind(str, Enum):
    PUBLIC_TENDER = "public_tender"
    PROCUREMENT_PLATFORM = "procurement_platform"
    DIRECT = "direct"
    BROKER = "broker"
    EMAIL_FORWARDED = "email_forwarded"
    FORWARDED = "forwarded"
    MANUAL = "manual"
    UNKNOWN = "unknown"


def infer_source_kind(
    source_type: str | None, source_name: str | None, metadata: dict | None = None
) -> SourceKind:
    metadata = metadata or {}
    source_type_value = normalize_text(source_type)
    source_name_value = normalize_text(source_name)
    fingerprint = " ".join(
        value
        for value in (
            source_type_value,
            source_name_value,
            normalize_text(metadata.get("platform")),
            normalize_text(metadata.get("host")),
            normalize_text(metadata.get("origin")),
        )
        if value
    )

    if "doffin" in fingerprint:
        return SourceKind.PUBLIC_TENDER
    if source_type_value == "email":
        return SourceKind.EMAIL_FORWARDED
    if source_type_value == "procurement":
        return SourceKind.PROCUREMENT_PLATFORM
    if "procurement" in fingerprint or "anskaff" in fingerprint:
        return SourceKind.PROCUREMENT_PLATFORM
    if "forwarded" in fingerprint or "forward" in fingerprint:
        return SourceKind.FORWARDED
    if source_type_value in {"scraper", "broker"}:
        return SourceKind.BROKER
    if "direct" in fingerprint:
        return SourceKind.DIRECT
    if "manual" in fingerprint:
        return SourceKind.MANUAL
    return SourceKind.UNKNOWN
