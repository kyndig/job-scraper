from __future__ import annotations

import re

from job_scraper.kois.schema import ExtractedRecord, RawSourceItem
from job_scraper.kois.utils import normalize_text


AGREEMENT_PHRASES = (
    "dps",
    "dynamic purchasing system",
    "frame",
    "frame agreement",
    "framework",
    "framework agreement",
    "ramme",
    "rammeavtale",
    "ramme avtale",
)


def _contains_agreement_phrase(text: str | None) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    # Procurement feeds often provide compact agreement labels ("frame", "dps").
    if normalized in AGREEMENT_PHRASES:
        return True
    return any(
        re.search(rf"\b{re.escape(keyword)}\b", normalized) for keyword in AGREEMENT_PHRASES
    )


def _looks_like_agreement(
    metadata: dict, notice_payload: dict, record: ExtractedRecord
) -> bool:
    agreement_type = normalize_text(
        notice_payload.get("agreement_type")
        or metadata.get("agreement_type")
        or record.extracted_data.get("agreement_type")
    )
    notice_type = normalize_text(
        notice_payload.get("notice_type")
        or metadata.get("notice_type")
        or record.extracted_data.get("notice_type")
    )
    title = normalize_text(notice_payload.get("title") or record.title)
    return any(
        (
            _contains_agreement_phrase(agreement_type),
            _contains_agreement_phrase(notice_type),
            _contains_agreement_phrase(title),
        )
    )


def build_agreement_signal_payload(
    raw_item: RawSourceItem, record: ExtractedRecord
) -> dict | None:
    if raw_item.source_type != "procurement":
        return None
    metadata = raw_item.metadata_json or {}
    notice_payload = metadata.get("notice_payload") or {}
    if not _looks_like_agreement(metadata, notice_payload, record):
        return None
    return {
        "raw_source_item_id": raw_item.id,
        "source_name": raw_item.source_name,
        "external_id": raw_item.external_id,
        "title": record.title,
        "buyer_name": record.customer,
        "agreement_type": normalize_text(
            notice_payload.get("agreement_type")
            or record.extracted_data.get("agreement_type")
            or "unspecified"
        ),
        "category": notice_payload.get("category") or record.extracted_data.get("category"),
        "status": normalize_text(notice_payload.get("status")),
        "source_url": record.source_url,
        "published_at": notice_payload.get("published_at"),
        "deadline": record.deadline,
        "signal_confidence": record.extraction_confidence or 0.6,
        "metadata_json": {
            "source_kind": record.extracted_data.get("source_kind"),
            "notice_type": notice_payload.get("notice_type"),
            "raw_source_type": raw_item.source_type,
        },
    }
