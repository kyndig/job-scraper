from __future__ import annotations

from job_scraper.kois.schema import ExtractedRecord, RawSourceItem
from job_scraper.kois.utils import normalize_text


AGREEMENT_KEYWORDS = ("dps", "frame", "framework", "agreement", "rammeavtale")


def _looks_like_agreement(metadata: dict, record: ExtractedRecord) -> bool:
    agreement_type = normalize_text(metadata.get("agreement_type"))
    notice_type = normalize_text(metadata.get("notice_type"))
    haystack = " ".join(
        value
        for value in (
            agreement_type,
            notice_type,
            normalize_text(record.title),
            normalize_text(record.description),
        )
        if value
    )
    return any(keyword in haystack for keyword in AGREEMENT_KEYWORDS)


def build_agreement_signal_payload(
    raw_item: RawSourceItem, record: ExtractedRecord
) -> dict | None:
    metadata = raw_item.metadata_json or {}
    if not _looks_like_agreement(metadata, record):
        return None
    notice_payload = metadata.get("notice_payload") or {}
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
