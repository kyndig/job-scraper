from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_scraper.kois.schema import (
    AgreementGap,
    AgreementSignal,
    ClusterSource,
    ExtractedRecord,
    GapStatus,
    OpportunityCluster,
    SourceComparison,
)


def buyer_trends(session: Session, limit: int = 10) -> list[dict]:
    rows = session.execute(
        select(
            OpportunityCluster.customer.label("buyer"),
            func.count(OpportunityCluster.id).label("opportunity_count"),
            func.avg(OpportunityCluster.confidence).label("avg_confidence"),
        )
        .where(OpportunityCluster.customer.is_not(None))
        .group_by(OpportunityCluster.customer)
        .order_by(func.count(OpportunityCluster.id).desc())
        .limit(limit)
    )
    return [
        {
            "buyer": row.buyer,
            "opportunity_count": int(row.opportunity_count),
            "avg_confidence": float(row.avg_confidence or 0.0),
        }
        for row in rows
    ]


def broker_patterns(session: Session, limit: int = 10) -> list[dict]:
    rows = session.execute(
        select(
            ExtractedRecord.broker.label("broker"),
            func.count(ExtractedRecord.id).label("record_count"),
            func.count(func.distinct(ExtractedRecord.customer)).label("unique_buyers"),
        )
        .where(ExtractedRecord.broker.is_not(None))
        .group_by(ExtractedRecord.broker)
        .order_by(func.count(ExtractedRecord.id).desc())
        .limit(limit)
    )
    return [
        {
            "broker": row.broker,
            "record_count": int(row.record_count),
            "unique_buyers": int(row.unique_buyers),
        }
        for row in rows
    ]


def source_quality_summary(session: Session) -> dict:
    cluster_count = session.execute(
        select(func.count(OpportunityCluster.id))
    ).scalar_one()
    comparison_cluster_count = session.execute(
        select(func.count(func.distinct(SourceComparison.opportunity_cluster_id)))
    ).scalar_one()
    source_counts = (
        select(
            ClusterSource.opportunity_cluster_id,
            func.count(ClusterSource.id).label("count_per_cluster"),
        )
        .group_by(ClusterSource.opportunity_cluster_id)
        .subquery()
    )
    avg_source_count = session.execute(
        select(func.avg(source_counts.c.count_per_cluster))
    ).scalar_one_or_none()
    comparison_ratio = (
        float(comparison_cluster_count) / float(cluster_count)
        if cluster_count
        else 0.0
    )
    return {
        "cluster_count": int(cluster_count),
        "clusters_with_conflicts": int(comparison_cluster_count),
        "conflict_ratio": comparison_ratio,
        "average_sources_per_cluster": float(avg_source_count or 0.0),
    }


def agreement_coverage_summary(session: Session) -> dict:
    signal_count = session.execute(select(func.count(AgreementSignal.id))).scalar_one()
    gap_count = session.execute(select(func.count(AgreementGap.id))).scalar_one()
    open_gap_count = session.execute(
        select(func.count(AgreementGap.id)).where(AgreementGap.status == GapStatus.OPEN)
    ).scalar_one()
    return {
        "agreement_signal_count": int(signal_count),
        "gap_count": int(gap_count),
        "open_gap_count": int(open_gap_count),
    }


def phase2_summary(session: Session) -> dict:
    return {
        "buyer_trends": buyer_trends(session),
        "broker_patterns": broker_patterns(session),
        "source_quality": source_quality_summary(session),
        "coverage": agreement_coverage_summary(session),
    }
