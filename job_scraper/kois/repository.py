from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_scraper.kois.domain import RawIngestionItem
from job_scraper.kois.schema import (
    ClusterSource,
    DigestItem,
    ExtractedRecord,
    OpportunityCluster,
    RawSourceItem,
    ReviewState,
    ReviewStatus,
    SourceComparison,
)
from job_scraper.kois.utils import content_hash

AUTOMATED_REVIEW_STATUSES = frozenset(
    {ReviewStatus.AUTO_ACCEPTED, ReviewStatus.NEEDS_REVIEW}
)


def upsert_raw_source_item(session: Session, item: RawIngestionItem) -> RawSourceItem:
    item_hash = content_hash(item.raw_body)
    existing = session.execute(
        select(RawSourceItem).where(RawSourceItem.content_hash == item_hash)
    ).scalar_one_or_none()
    if existing:
        return existing

    raw = RawSourceItem(
        source_type=item.source_type,
        source_name=item.source_name,
        external_id=item.external_id,
        content_hash=item_hash,
        received_at=item.received_at,
        raw_body=item.raw_body,
        metadata_json=item.metadata,
    )
    session.add(raw)
    session.flush()
    return raw


def get_extracted_record_for_raw_source(
    session: Session, raw_source_item_id: int
) -> ExtractedRecord | None:
    return session.execute(
        select(ExtractedRecord)
        .where(ExtractedRecord.raw_source_item_id == raw_source_item_id)
        .order_by(ExtractedRecord.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def create_extracted_record(session: Session, payload: dict) -> ExtractedRecord:
    record = ExtractedRecord(**payload)
    session.add(record)
    session.flush()
    return record


def create_or_update_cluster(
    session: Session,
    cluster_key: str,
    title: str | None,
    customer: str | None,
    confidence: float,
    review_status: ReviewStatus,
) -> OpportunityCluster:
    cluster = session.execute(
        select(OpportunityCluster).where(OpportunityCluster.cluster_key == cluster_key)
    ).scalar_one_or_none()
    if cluster:
        cluster.title = cluster.title or title
        cluster.customer = cluster.customer or customer
        cluster.confidence = max(cluster.confidence, confidence)
        if cluster.review_status in AUTOMATED_REVIEW_STATUSES:
            cluster.review_status = review_status
        session.flush()
        return cluster

    cluster = OpportunityCluster(
        cluster_key=cluster_key,
        title=title,
        customer=customer,
        confidence=confidence,
        review_status=review_status,
    )
    session.add(cluster)
    session.flush()
    return cluster


def attach_cluster_source(
    session: Session,
    cluster: OpportunityCluster,
    record: ExtractedRecord,
    confidence: float,
    rationale: str,
) -> ClusterSource:
    existing = session.execute(
        select(ClusterSource).where(
            ClusterSource.opportunity_cluster_id == cluster.id,
            ClusterSource.extracted_record_id == record.id,
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    source = ClusterSource(
        opportunity_cluster_id=cluster.id,
        extracted_record_id=record.id,
        match_confidence=confidence,
        match_rationale=rationale,
    )
    session.add(source)
    session.flush()
    return source


def create_source_comparison(
    session: Session, cluster: OpportunityCluster, field_name: str, values: dict
) -> SourceComparison:
    comparison = SourceComparison(
        opportunity_cluster_id=cluster.id,
        field_name=field_name,
        values_json=values,
    )
    session.add(comparison)
    session.flush()
    return comparison


def upsert_source_comparison(
    session: Session, cluster: OpportunityCluster, field_name: str, values: dict
) -> SourceComparison:
    comparison = session.execute(
        select(SourceComparison).where(
            SourceComparison.opportunity_cluster_id == cluster.id,
            SourceComparison.field_name == field_name,
        )
    ).scalar_one_or_none()
    if comparison:
        comparison.values_json = values
        session.flush()
        return comparison
    return create_source_comparison(session, cluster, field_name, values)


def create_review_state(
    session: Session,
    cluster: OpportunityCluster,
    status: ReviewStatus,
    actor: str = "system",
    note: str | None = None,
) -> ReviewState:
    review = ReviewState(
        opportunity_cluster_id=cluster.id,
        status=status,
        actor=actor,
        note=note,
    )
    session.add(review)
    session.flush()
    cluster.review_status = status
    return review


def create_digest_item(
    session: Session,
    cluster: OpportunityCluster,
    status: ReviewStatus,
    payload: dict,
) -> DigestItem:
    existing_unsent = session.execute(
        select(DigestItem)
        .where(
            DigestItem.opportunity_cluster_id == cluster.id,
            DigestItem.sent_at.is_(None),
        )
        .order_by(DigestItem.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if existing_unsent:
        existing_unsent.review_status = status
        existing_unsent.payload_json = payload
        session.flush()
        return existing_unsent

    existing_sent = session.execute(
        select(DigestItem).where(
            DigestItem.opportunity_cluster_id == cluster.id,
            DigestItem.sent_at.is_not(None),
        )
        .order_by(DigestItem.sent_at.desc(), DigestItem.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if existing_sent:
        return existing_sent

    item = DigestItem(
        opportunity_cluster_id=cluster.id,
        review_status=status,
        payload_json=payload,
    )
    session.add(item)
    session.flush()
    return item


def mark_digest_sent(session: Session, item: DigestItem, slack_ts: str | None) -> None:
    item.slack_message_ts = slack_ts
    item.sent_at = datetime.now(timezone.utc)
    session.flush()
