from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_scraper.kois.config import KOISSettings, get_settings
from job_scraper.kois.filtering import OpportunityFilterPolicy
from job_scraper.kois.repository import (
    create_digest_item,
    delete_unsent_digest_items,
    mark_digest_sent,
)
from job_scraper.kois.schema import DigestItem, OpportunityCluster
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
    role_category: str | None
    role_tags: list[str]
    relevance_score: float
    relevance_rationale: str | None


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
        role_category=cluster.role_category,
        role_tags=cluster.role_tags_json or [],
        relevance_score=cluster.relevance_score,
        relevance_rationale=cluster.relevance_rationale,
    )


def select_digest_candidates(
    clusters: list[OpportunityCluster], policy: OpportunityFilterPolicy
) -> list[OpportunityCluster]:
    candidates: list[OpportunityCluster] = []
    for cluster in clusters:
        if not policy.should_include_digest(cluster):
            continue
        candidates.append(cluster)
    return candidates


def _cadence_blocked(session: Session, cadence_minutes: int) -> bool:
    if cadence_minutes <= 0:
        return False
    latest_sent_at = session.execute(
        select(DigestItem.sent_at)
        .where(DigestItem.sent_at.is_not(None))
        .order_by(DigestItem.sent_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest_sent_at is None:
        return False
    if latest_sent_at.tzinfo is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        now = datetime.now(timezone.utc)
    return latest_sent_at > (now - timedelta(minutes=cadence_minutes))


def send_digest_items(
    session: Session,
    clusters: list[OpportunityCluster],
    slack: SlackPoster,
    live_posting: bool,
    channel: str,
    settings: KOISSettings | None = None,
    policy: OpportunityFilterPolicy | None = None,
) -> list[dict]:
    settings = settings or get_settings()
    policy = policy or OpportunityFilterPolicy(settings)
    cadence_minutes = int(getattr(settings, "digest_cadence_minutes", 0))
    cadence_blocked = _cadence_blocked(session, cadence_minutes)
    sent_payloads: list[dict] = []
    for cluster in clusters:
        evaluation = policy.apply_to_cluster(cluster)
        if not cluster.sources:
            delete_unsent_digest_items(session, cluster)
            continue
        if not policy.should_include_digest(
            cluster, evaluated_relevance=evaluation.relevance_score
        ):
            delete_unsent_digest_items(session, cluster)
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
        if cadence_blocked:
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
