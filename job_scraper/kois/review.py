from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_scraper.kois.repository import create_review_state, get_cluster
from job_scraper.kois.schema import OpportunityCluster, ReviewStatus


def cluster_detail_payload(cluster: OpportunityCluster) -> dict:
    sources = []
    for link in cluster.sources:
        record = link.record
        raw = record.raw_source if record is not None else None
        snippet = (raw.raw_body or "")[:800] if raw is not None else ""
        sources.append(
            {
                "record_id": record.id if record is not None else None,
                "title": record.title if record is not None else None,
                "customer": record.customer if record is not None else None,
                "broker": record.broker if record is not None else None,
                "source_url": record.source_url if record is not None else None,
                "source_type": raw.source_type if raw is not None else None,
                "source_name": raw.source_name if raw is not None else None,
                "match_confidence": link.match_confidence,
                "raw_snippet": snippet,
            }
        )
    return {
        "id": cluster.id,
        "cluster_key": cluster.cluster_key,
        "title": cluster.title,
        "customer": cluster.customer,
        "review_status": cluster.review_status.value,
        "confidence": cluster.confidence,
        "primary_source_record_id": cluster.primary_source_record_id,
        "role_category": cluster.role_category,
        "relevance_score": cluster.relevance_score,
        "sources": sources,
        "comparisons": [
            {"field": comparison.field_name, "values": comparison.values_json}
            for comparison in cluster.comparisons
        ],
    }


class ReviewService:
    def __init__(self, session: Session):
        self.session = session

    def list_needs_review(self) -> list[OpportunityCluster]:
        return list(
            self.session.execute(
                select(OpportunityCluster).where(
                    OpportunityCluster.review_status == ReviewStatus.NEEDS_REVIEW
                )
            ).scalars()
        )

    def get_cluster(self, cluster_id: int) -> OpportunityCluster:
        cluster = get_cluster(self.session, cluster_id)
        if not cluster:
            raise ValueError(f"Cluster {cluster_id} not found")
        return cluster

    def set_status(
        self,
        cluster_id: int,
        status: ReviewStatus,
        actor: str = "reviewer",
        note: str | None = None,
    ) -> OpportunityCluster:
        cluster = self.session.get(OpportunityCluster, cluster_id)
        if not cluster:
            raise ValueError(f"Cluster {cluster_id} not found")
        create_review_state(
            session=self.session,
            cluster=cluster,
            status=status,
            actor=actor,
            note=note,
        )
        self.session.commit()
        self.session.refresh(cluster)
        return cluster
