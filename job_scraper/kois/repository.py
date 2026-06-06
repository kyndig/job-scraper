from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_scraper.kois.domain import RawIngestionItem
from job_scraper.kois.schema import (
    AgreementGap,
    AgreementSignal,
    ClusterSource,
    DigestItem,
    ExtractedRecord,
    GapStatus,
    OpportunityCluster,
    RawSourceItem,
    ReviewState,
    ReviewStatus,
    SourceComparison,
)
from job_scraper.kois.utils import content_hash

AGREEMENT_GAP_AUTO_CLOSE_NOTE = (
    "Auto-closed after matching agreement signal detected for this buyer."
)

AUTOMATED_REVIEW_STATUSES = frozenset(
    {ReviewStatus.AUTO_ACCEPTED, ReviewStatus.NEEDS_REVIEW}
)


def upsert_raw_source_item(session: Session, item: RawIngestionItem) -> RawSourceItem:
    item_hash = content_hash(item.raw_body)
    existing_by_external_id = session.execute(
        select(RawSourceItem).where(
            RawSourceItem.source_type == item.source_type,
            RawSourceItem.source_name == item.source_name,
            RawSourceItem.external_id == item.external_id,
        )
    ).scalar_one_or_none()
    if existing_by_external_id:
        if existing_by_external_id.content_hash != item_hash:
            existing_by_external_id.content_hash = item_hash
            existing_by_external_id.raw_body = item.raw_body
            existing_by_external_id.metadata_json = item.metadata
            existing_by_external_id.received_at = item.received_at
            existing_by_external_id.extraction_error = None
            session.flush()
        return existing_by_external_id

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


def detach_record_cluster_sources(
    session: Session, record: ExtractedRecord
) -> list[OpportunityCluster]:
    links = list(
        session.execute(
            select(ClusterSource).where(ClusterSource.extracted_record_id == record.id)
        ).scalars()
    )
    affected_clusters = []
    for link in links:
        affected_clusters.append(link.cluster)
        session.delete(link)
    if links:
        session.flush()
        for cluster in affected_clusters:
            session.expire(cluster, ["sources"])
    return affected_clusters


def detach_superseded_cluster_sources(
    session: Session, record: ExtractedRecord
) -> list[OpportunityCluster]:
    stale_links = list(
        session.execute(
            select(ClusterSource)
            .join(ExtractedRecord)
            .where(
                ExtractedRecord.raw_source_item_id == record.raw_source_item_id,
                ClusterSource.extracted_record_id != record.id,
            )
        ).scalars()
    )
    affected_clusters = []
    for link in stale_links:
        affected_clusters.append(link.cluster)
        session.delete(link)
    if stale_links:
        session.flush()
        for cluster in affected_clusters:
            session.expire(cluster, ["sources"])
    return affected_clusters


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


def delete_unsent_digest_items(session: Session, cluster: OpportunityCluster) -> None:
    unsent_items = session.execute(
        select(DigestItem).where(
            DigestItem.opportunity_cluster_id == cluster.id,
            DigestItem.sent_at.is_(None),
        )
    ).scalars()
    for item in unsent_items:
        session.delete(item)
    session.flush()


def list_clusters_with_unsent_digests(session: Session) -> list[OpportunityCluster]:
    return list(
        session.execute(
            select(OpportunityCluster)
            .join(DigestItem, DigestItem.opportunity_cluster_id == OpportunityCluster.id)
            .where(DigestItem.sent_at.is_(None))
            .distinct()
        ).scalars()
    )


def upsert_agreement_signal(session: Session, payload: dict) -> AgreementSignal:
    existing = session.execute(
        select(AgreementSignal).where(
            AgreementSignal.source_name == payload["source_name"],
            AgreementSignal.external_id == payload["external_id"],
        )
    ).scalar_one_or_none()
    if existing:
        existing.raw_source_item_id = payload["raw_source_item_id"]
        existing.title = payload.get("title")
        existing.buyer_name = payload.get("buyer_name")
        existing.agreement_type = payload.get("agreement_type")
        existing.category = payload.get("category")
        existing.status = payload.get("status")
        existing.source_url = payload.get("source_url")
        existing.published_at = payload.get("published_at")
        existing.deadline = payload.get("deadline")
        existing.signal_confidence = payload.get("signal_confidence", 0.0)
        existing.metadata_json = payload.get("metadata_json", {})
        session.flush()
        return existing

    created = AgreementSignal(**payload)
    session.add(created)
    session.flush()
    return created


def delete_agreement_signal(
    session: Session, *, source_name: str, external_id: str
) -> bool:
    existing = session.execute(
        select(AgreementSignal).where(
            AgreementSignal.source_name == source_name,
            AgreementSignal.external_id == external_id,
        )
    ).scalar_one_or_none()
    if existing is None:
        return False
    session.delete(existing)
    session.flush()
    return True


def list_agreement_signals(
    session: Session,
    buyer_name: str | None = None,
    agreement_type: str | None = None,
    limit: int = 50,
) -> list[AgreementSignal]:
    query = select(AgreementSignal).order_by(AgreementSignal.updated_at.desc())
    if buyer_name:
        query = query.where(AgreementSignal.buyer_name.ilike(f"%{buyer_name}%"))
    if agreement_type:
        query = query.where(AgreementSignal.agreement_type == agreement_type)
    return list(session.execute(query.limit(limit)).scalars())


def upsert_agreement_gap(session: Session, payload: dict) -> AgreementGap:
    existing = session.execute(
        select(AgreementGap).where(AgreementGap.gap_key == payload["gap_key"])
    ).scalar_one_or_none()
    if existing:
        existing.buyer_name = payload["buyer_name"]
        existing.confidence = payload["confidence"]
        existing.rationale = payload["rationale"]
        existing.evidence_json = payload["evidence_json"]
        if existing.status == GapStatus.OPEN:
            existing.status = payload.get("status", GapStatus.OPEN)
        elif (
            existing.status == GapStatus.IGNORED
            and existing.note == AGREEMENT_GAP_AUTO_CLOSE_NOTE
        ):
            existing.status = payload.get("status", GapStatus.OPEN)
            if existing.status == GapStatus.OPEN:
                existing.note = None
        session.flush()
        return existing

    created = AgreementGap(**payload)
    session.add(created)
    session.flush()
    return created


def list_agreement_gaps(
    session: Session, status: GapStatus | None = None
) -> list[AgreementGap]:
    query = select(AgreementGap).order_by(AgreementGap.confidence.desc(), AgreementGap.id.desc())
    if status:
        query = query.where(AgreementGap.status == status)
    return list(session.execute(query).scalars())
