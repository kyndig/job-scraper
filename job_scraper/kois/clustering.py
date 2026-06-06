from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_scraper.kois.extraction import make_cluster_key
from job_scraper.kois.repository import (
    attach_cluster_source,
    create_or_update_cluster,
    detach_superseded_cluster_sources,
    upsert_source_comparison,
)
from job_scraper.kois.schema import (
    ExtractedRecord,
    OpportunityCluster,
    ReviewStatus,
    SourceComparison,
)
from job_scraper.kois.utils import normalize_text, normalize_url


SOURCE_PRIORITY = {
    "doffin": 100,
    "procurement": 90,
    "direct": 80,
    "broker": 70,
    "email": 60,
    "forwarded": 50,
    "manual": 40,
    "unknown": 10,
}


def _source_priority_key(record: ExtractedRecord) -> str:
    extracted_data = record.extracted_data or {}
    source_type = normalize_text(extracted_data.get("source_type"))
    platform = normalize_text(extracted_data.get("platform"))
    host = normalize_text(extracted_data.get("host"))
    broker = normalize_text(record.broker)
    source_url = normalize_text(record.source_url)
    fingerprint = " ".join(
        part for part in (source_type, platform, host, broker, source_url) if part
    )

    if "doffin" in fingerprint:
        return "doffin"
    if "procurement" in fingerprint:
        return "procurement"
    if source_type == "email" or "@" in broker:
        return "email"
    if "forwarded" in fingerprint or "forward" in fingerprint:
        return "forwarded"
    if "manual" in fingerprint:
        return "manual"
    if source_type == "scraper" or "broker" in fingerprint:
        return "broker"
    if "direct" in fingerprint:
        return "direct"
    return "unknown"


def _source_rank(record: ExtractedRecord) -> int:
    return SOURCE_PRIORITY[_source_priority_key(record)]


def _similarity(record: ExtractedRecord, cluster: OpportunityCluster) -> tuple[float, str]:
    score = 0.0
    parts = []
    if normalize_url(record.source_url) and cluster.cluster_key == normalize_url(record.source_url):
        score += 0.6
        parts.append("url")
    if normalize_text(record.title) == normalize_text(cluster.title):
        score += 0.2
        parts.append("title")
    if normalize_text(record.customer) == normalize_text(cluster.customer):
        score += 0.1
        parts.append("customer")
    if normalize_text(record.deadline):
        score += 0.1
        parts.append("deadline")
    return min(score, 1.0), ",".join(parts) or "weak-match"


def cluster_records(session: Session, records: list[ExtractedRecord]) -> list[OpportunityCluster]:
    clusters: list[OpportunityCluster] = []
    for record in records:
        key = make_cluster_key(
            {
                "title": record.title,
                "customer": record.customer,
                "deadline": record.deadline,
                "source_url": record.source_url,
            }
        )
        confidence = 0.95 if normalize_url(record.source_url) else 0.7
        review_status = (
            ReviewStatus.AUTO_ACCEPTED if confidence >= 0.9 else ReviewStatus.NEEDS_REVIEW
        )
        cluster = create_or_update_cluster(
            session=session,
            cluster_key=key,
            title=record.title,
            customer=record.customer,
            confidence=confidence,
            review_status=review_status,
        )
        clusters.extend(detach_superseded_cluster_sources(session, record))
        match_confidence, rationale = _similarity(record, cluster)
        attach_cluster_source(session, cluster, record, match_confidence, rationale)
        clusters.append(cluster)

    _refresh_comparisons(session, clusters)
    _refresh_primary_sources(session, clusters)
    return clusters


def _refresh_comparisons(session: Session, clusters: list[OpportunityCluster]) -> None:
    unique_clusters = {cluster.id: cluster for cluster in clusters}.values()
    for cluster in unique_clusters:
        records = [source.record for source in cluster.sources]
        field_values: dict[str, set[str]] = defaultdict(set)
        for record in records:
            for field_name in ("title", "customer", "broker", "deadline", "source_url"):
                value = getattr(record, field_name, None)
                if value:
                    field_values[field_name].add(value)

        divergent_values = {
            field_name: values for field_name, values in field_values.items() if len(values) > 1
        }
        existing_comparisons = list(
            session.execute(
                select(SourceComparison).where(
                    SourceComparison.opportunity_cluster_id == cluster.id
                )
            ).scalars()
        )
        for comparison in existing_comparisons:
            if comparison.field_name not in divergent_values:
                session.delete(comparison)

        for field_name, values in divergent_values.items():
            upsert_source_comparison(
                session=session,
                cluster=cluster,
                field_name=field_name,
                values={"values": sorted(values)},
            )
        session.flush()


def _refresh_primary_sources(session: Session, clusters: list[OpportunityCluster]) -> None:
    unique_clusters = {cluster.id: cluster for cluster in clusters}.values()
    for cluster in unique_clusters:
        sources = [source.record for source in cluster.sources]
        if not sources:
            cluster.primary_source_record_id = None
            session.flush()
            continue
        primary = sorted(
            sources,
            key=lambda record: (
                _source_rank(record),
                record.extraction_confidence or 0.0,
                record.id,
            ),
            reverse=True,
        )[0]
        cluster.primary_source_record_id = primary.id
        session.flush()
