from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_scraper.kois.repository import create_review_state
from job_scraper.kois.schema import OpportunityCluster, ReviewStatus


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
