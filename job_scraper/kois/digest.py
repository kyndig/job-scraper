from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from job_scraper.kois.repository import create_digest_item, mark_digest_sent
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


def cluster_to_payload(cluster: OpportunityCluster) -> DigestPayload:
    return DigestPayload(
        title=cluster.title or "Untitled opportunity",
        customer=cluster.customer,
        deadline=cluster.sources[0].record.deadline if cluster.sources else None,
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
    for cluster in select_digest_candidates(clusters):
        payload = cluster_to_payload(cluster)
        digest_item = create_digest_item(
            session=session,
            cluster=cluster,
            status=cluster.review_status,
            payload=payload.__dict__,
        )
        if digest_item.sent_at is not None:
            continue

        slack_ts = None
        if live_posting:
            response = slack.post_digest(payload.__dict__, channel=channel)
            slack_ts = None if response is None else response.get("ts")

        mark_digest_sent(session, digest_item, slack_ts)
        sent_payloads.append(payload.__dict__)
    return sent_payloads
