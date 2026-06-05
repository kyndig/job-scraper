from __future__ import annotations

import re
from urllib.parse import urlparse

from job_scraper.models import Job
from job_scraper.kois.schema import RawSourceItem
from job_scraper.kois.utils import normalize_text
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
            "extracted_data": {"source_type": "email", "metadata": metadata},
        }

    def _extract_scraper(self, raw_source: RawSourceItem) -> dict:
        job = Job.model_validate_json(raw_source.raw_body)
        description = job.description or ""
        summary = job.description_summarised
        if not summary and self.summarizer:
            summary = self.summarizer.summarize(description)
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
            },
        }

    def extract(self, raw_source: RawSourceItem) -> dict:
        if raw_source.source_type == "email":
            return self._extract_email(raw_source)

        return self._extract_scraper(raw_source)


def make_cluster_key(payload: dict) -> str:
    source_url = normalize_text(payload.get("source_url"))
    if source_url:
        return source_url

    title = normalize_text(payload.get("title"))
    customer = normalize_text(payload.get("customer"))
    deadline = normalize_text(payload.get("deadline"))
    return "|".join([title, customer, deadline])
