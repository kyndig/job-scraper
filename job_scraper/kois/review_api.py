from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from job_scraper.kois.db import get_db_session
from job_scraper.kois.review import ReviewService
from job_scraper.kois.schema import OpportunityCluster, ReviewStatus

app = FastAPI(title="KOIS Phase 1 Review API")


class ReviewUpdate(BaseModel):
    status: ReviewStatus
    actor: str = "reviewer"
    note: str | None = None


@app.get("/health")
def healthcheck():
    return {"ok": True}


@app.get("/clusters")
def list_clusters(
    status: ReviewStatus | None = None,
    q: str | None = None,
    session: Session = Depends(get_db_session),
):
    query = select(OpportunityCluster)
    if status:
        query = query.where(OpportunityCluster.review_status == status)
    if q:
        query = query.where(
            or_(
                OpportunityCluster.title.ilike(f"%{q}%"),
                OpportunityCluster.customer.ilike(f"%{q}%"),
                OpportunityCluster.cluster_key.ilike(f"%{q}%"),
            )
        )
    clusters = list(session.execute(query).scalars())
    return [
        {
            "id": cluster.id,
            "cluster_key": cluster.cluster_key,
            "title": cluster.title,
            "customer": cluster.customer,
            "review_status": cluster.review_status.value,
            "confidence": cluster.confidence,
            "source_count": len(cluster.sources),
        }
        for cluster in clusters
    ]


@app.get("/review-queue")
def review_queue(session: Session = Depends(get_db_session)):
    review_service = ReviewService(session)
    clusters = review_service.list_needs_review()
    return [
        {
            "id": cluster.id,
            "title": cluster.title,
            "customer": cluster.customer,
            "confidence": cluster.confidence,
            "comparisons": [
                {"field": comparison.field_name, "values": comparison.values_json}
                for comparison in cluster.comparisons
            ],
        }
        for cluster in clusters
    ]


@app.patch("/clusters/{cluster_id}/status")
def update_cluster_status(
    cluster_id: int,
    update: ReviewUpdate,
    session: Session = Depends(get_db_session),
):
    review_service = ReviewService(session)
    try:
        cluster = review_service.set_status(
            cluster_id=cluster_id,
            status=update.status,
            actor=update.actor,
            note=update.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "id": cluster.id,
        "status": cluster.review_status.value,
    }
