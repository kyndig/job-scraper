from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from job_scraper.kois.repository import (
    create_digest_item,
    delete_unsent_digest_items,
    mark_digest_sent,
)
from job_scraper.kois.schema import OpportunityCluster, ReviewStatus
from job_scraper.slack_poster import SlackPoster


@dataclass
class DigestPayload:
    title: str
    customer: str | None
    deadline: str | None
    source_count: int
    primary_source_record_id: int | None
    confidence: float
    review_status: str
    cluster_id: int


def _resolve_primary_record(cluster: OpportunityCluster):
    if not cluster.sources:
        return None

    if cluster.primary_source_record_id is not None:
        for source in cluster.sources:
            if source.extracted_record_id == cluster.primary_source_record_id:
                return source.record

    return cluster.sources[0].record


def cluster_to_payload(cluster: OpportunityCluster) -> DigestPayload:
    primary_record = _resolve_primary_record(cluster)
    return DigestPayload(
        title=(primary_record.title if primary_record else None)
        or cluster.title
        or "Untitled opportunity",
        customer=(primary_record.customer if primary_record else None) or cluster.customer,
        deadline=primary_record.deadline if primary_record else None,
        source_count=len(cluster.sources),
        primary_source_record_id=cluster.primary_source_record_id,
        confidence=cluster.confidence,
        review_status=cluster.review_status.value,
        cluster_id=cluster.id,
    )


def select_digest_candidates(clusters: list[OpportunityCluster]) -> list[OpportunityCluster]:
    candidates: list[OpportunityCluster] = []
    for cluster in clusters:
        if cluster.review_status in (ReviewStatus.IGNORED, ReviewStatus.WATCH_ONLY):
            continue
        if cluster.review_status == ReviewStatus.NEEDS_REVIEW and cluster.confidence < 0.75:
            continue
        candidates.append(cluster)
    return candidates


def send_digest_items(
    session: Session,
    clusters: list[OpportunityCluster],
    slack: SlackPoster,
    live_posting: bool,
    channel: str,
) -> list[dict]:
    sent_payloads: list[dict] = []
    for cluster in clusters:
        if not cluster.sources:
            delete_unsent_digest_items(session, cluster)
            continue
        if cluster.review_status in (ReviewStatus.IGNORED, ReviewStatus.WATCH_ONLY):
            delete_unsent_digest_items(session, cluster)
            continue
        if cluster.review_status == ReviewStatus.NEEDS_REVIEW and cluster.confidence < 0.75:
            continue

        payload = cluster_to_payload(cluster)
        digest_item = create_digest_item(
            session=session,
            cluster=cluster,
            status=cluster.review_status,
            payload=payload.__dict__,
        )
        if digest_item.sent_at is not None:
            continue

        if live_posting:
            response = slack.post_digest(payload.__dict__, channel=channel)
            if response is None:
                continue
            slack_ts = response.get("ts")
        else:
            slack_ts = None

        mark_digest_sent(session, digest_item, slack_ts)
        sent_payloads.append(payload.__dict__)
    return sent_payloads
