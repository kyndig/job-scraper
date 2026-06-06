from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from job_scraper.kois.config import KOISSettings
from job_scraper.kois.domain import RawIngestionItem
from job_scraper.kois.utils import content_hash, normalize_text


def _load_json_url(url: str) -> list[dict]:
    request = Request(url=url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=20) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict):
        return payload.get("items", [])
    if isinstance(payload, list):
        return payload
    return []


def _parse_embedded_json(payload: str | None) -> list[dict]:
    if not payload:
        return []
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        return parsed.get("items", [])
    if isinstance(parsed, list):
        return parsed
    return []


def _normalize_notice(source_name: str, notice: dict) -> RawIngestionItem:
    payload = dict(notice)
    external_id = (
        str(
            notice.get("id")
            or notice.get("notice_id")
            or notice.get("external_id")
            or notice.get("url")
            or content_hash(json.dumps(notice, sort_keys=True))
        )
    )
    title = notice.get("title")
    source_url = notice.get("url") or notice.get("source_url")
    metadata = {
        "title": title,
        "url": source_url,
        "buyer": notice.get("buyer") or notice.get("customer"),
        "agreement_type": normalize_text(notice.get("agreement_type")),
        "notice_type": normalize_text(notice.get("notice_type")),
        "category": notice.get("category"),
        "origin": source_name,
        "notice_payload": payload,
    }
    return RawIngestionItem(
        source_type="procurement",
        source_name=source_name,
        external_id=external_id,
        raw_body=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        metadata=metadata,
        received_at=datetime.now(timezone.utc),
    )


def fetch_procurement_items(settings: KOISSettings) -> list[RawIngestionItem]:
    notices_by_source: dict[str, list[dict]] = {}

    doffin_feed_json = getattr(settings, "doffin_feed_json", None)
    doffin_feed_url = getattr(settings, "doffin_feed_url", None)
    procurement_feed_json_by_source = getattr(
        settings, "procurement_feed_json_by_source", {}
    ) or {}
    procurement_feed_urls_by_source = getattr(
        settings, "procurement_feed_urls_by_source", {}
    ) or {}

    doffin_embedded = _parse_embedded_json(doffin_feed_json)
    if doffin_embedded:
        notices_by_source["doffin"] = doffin_embedded
    elif doffin_feed_url:
        try:
            notices_by_source["doffin"] = _load_json_url(doffin_feed_url)
        except Exception:  # noqa: BLE001
            notices_by_source["doffin"] = []

    for source_name, source_payload in procurement_feed_json_by_source.items():
        notices_by_source[source_name] = _parse_embedded_json(source_payload)

    for source_name, source_url in procurement_feed_urls_by_source.items():
        if source_name in notices_by_source and notices_by_source[source_name]:
            continue
        try:
            notices_by_source[source_name] = _load_json_url(source_url)
        except Exception:  # noqa: BLE001
            notices_by_source[source_name] = []

    raw_items: list[RawIngestionItem] = []
    for source_name, notices in notices_by_source.items():
        for notice in notices:
            if not isinstance(notice, dict):
                continue
            raw_items.append(_normalize_notice(source_name=source_name, notice=notice))
    return raw_items
