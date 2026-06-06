from __future__ import annotations

import re
from urllib.parse import urlparse

from job_scraper.kois.domain import infer_source_kind
from job_scraper.models import Job
from job_scraper.kois.schema import RawSourceItem
from job_scraper.kois.utils import normalize_text, normalize_url
from job_scraper.summarizer import JobDescriptionSummarizer


TITLE_PATTERN = re.compile(r"(oppdrag|assignment|rolle)[:\-]\s*(.+)", re.IGNORECASE)
DEADLINE_PATTERN = re.compile(r"(frist|deadline)[:\-]\s*([^\n]+)", re.IGNORECASE)
URL_PATTERN = re.compile(r"https?://[^\s)]+")


class RecordExtractor:
    def __init__(self, summarizer: JobDescriptionSummarizer | None = None):
        self.summarizer = summarizer

    def _extract_email(self, raw_source: RawSourceItem) -> dict:
        body = raw_source.raw_body
        metadata = raw_source.metadata_json or {}
        subject = metadata.get("subject")
        source_kind = infer_source_kind(
            raw_source.source_type,
            raw_source.source_name,
            metadata,
        )

        title_match = TITLE_PATTERN.search(subject or "") or TITLE_PATTERN.search(body)
        deadline_match = DEADLINE_PATTERN.search(body)
        url_match = URL_PATTERN.search(body)

        summary = None
        if self.summarizer:
            summary = self.summarizer.summarize(body)

        return {
            "raw_source_item_id": raw_source.id,
            "title": title_match.group(2).strip() if title_match else subject,
            "customer": metadata.get("from"),
            "broker": metadata.get("from"),
            "source_url": url_match.group(0) if url_match else None,
            "deadline": deadline_match.group(2).strip() if deadline_match else None,
            "description": body,
            "summary": summary,
            "extraction_confidence": 0.65,
            "extracted_data": {
                "source_type": "email",
                "metadata": metadata,
                "source_kind": source_kind.value,
                "raw_content_hash": raw_source.content_hash,
            },
        }

    def _extract_scraper(self, raw_source: RawSourceItem) -> dict:
        job = Job.model_validate_json(raw_source.raw_body)
        description = job.description or ""
        summary = job.description_summarised
        if not summary and self.summarizer:
            summary = self.summarizer.summarize(description)
        source_kind = infer_source_kind(
            raw_source.source_type,
            raw_source.source_name,
            raw_source.metadata_json,
        )
        return {
            "raw_source_item_id": raw_source.id,
            "title": job.job_overview.title,
            "customer": job.job_overview.company,
            "broker": job.platform,
            "source_url": job.job_overview.job_uri,
            "deadline": job.job_overview.delivery_date,
            "description": description,
            "summary": summary,
            "extraction_confidence": 0.9,
            "extracted_data": {
                "source_type": "scraper",
                "platform": job.platform,
                "host": urlparse(job.job_overview.job_uri or "").hostname,
                "source_kind": source_kind.value,
                "raw_content_hash": raw_source.content_hash,
            },
        }

    def _extract_procurement(self, raw_source: RawSourceItem) -> dict:
        metadata = raw_source.metadata_json or {}
        payload = metadata.get("notice_payload") or {}
        source_url = payload.get("url") or payload.get("source_url")
        source_kind = infer_source_kind(
            raw_source.source_type,
            raw_source.source_name,
            metadata,
        )

        return {
            "raw_source_item_id": raw_source.id,
            "title": payload.get("title") or metadata.get("title"),
            "customer": payload.get("buyer") or payload.get("customer"),
            "broker": raw_source.source_name,
            "source_url": source_url,
            "deadline": payload.get("deadline"),
            "description": payload.get("description") or raw_source.raw_body,
            "summary": payload.get("summary"),
            "extraction_confidence": 0.85,
            "extracted_data": {
                "source_type": "procurement",
                "source_kind": source_kind.value,
                "agreement_type": payload.get("agreement_type"),
                "notice_type": payload.get("notice_type"),
                "category": payload.get("category"),
                "host": urlparse(source_url or "").hostname,
                "raw_content_hash": raw_source.content_hash,
            },
        }

    def extract(self, raw_source: RawSourceItem) -> dict:
        if raw_source.source_type == "email":
            return self._extract_email(raw_source)
        if raw_source.source_type == "procurement":
            return self._extract_procurement(raw_source)

        return self._extract_scraper(raw_source)


def make_cluster_key(payload: dict) -> str:
    source_url = normalize_url(payload.get("source_url"))
    if source_url:
        return source_url

    title = normalize_text(payload.get("title"))
    customer = normalize_text(payload.get("customer"))
    deadline = normalize_text(payload.get("deadline"))
    return "|".join([title, customer, deadline])
