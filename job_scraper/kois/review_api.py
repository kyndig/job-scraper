from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from job_scraper.kois.analytics import phase2_summary
from job_scraper.kois.db import get_db_session
from job_scraper.kois.gaps import discover_missing_agreement_gaps, set_gap_status
from job_scraper.kois.repository import list_agreement_gaps, list_agreement_signals
from job_scraper.kois.review import ReviewService
from job_scraper.kois.schema import GapStatus, OpportunityCluster, ReviewStatus

app = FastAPI(title="KOIS Phase 2 Review And Intelligence API")


class ReviewUpdate(BaseModel):
    status: ReviewStatus
    actor: str = "reviewer"
    note: str | None = None


class GapStatusUpdate(BaseModel):
    status: GapStatus
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


@app.get("/analytics/summary")
def analytics_summary(session: Session = Depends(get_db_session)):
    return phase2_summary(session)


@app.get("/agreement-signals")
def agreement_signals(
    buyer: str | None = None,
    agreement_type: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_db_session),
):
    signals = list_agreement_signals(
        session=session,
        buyer_name=buyer,
        agreement_type=agreement_type,
        limit=limit,
    )
    return [
        {
            "id": signal.id,
            "source_name": signal.source_name,
            "external_id": signal.external_id,
            "title": signal.title,
            "buyer_name": signal.buyer_name,
            "agreement_type": signal.agreement_type,
            "category": signal.category,
            "status": signal.status,
            "source_url": signal.source_url,
            "confidence": signal.signal_confidence,
        }
        for signal in signals
    ]


@app.post("/agreement-gaps/discover")
def discover_agreement_gaps(
    min_cluster_hits: int = 2,
    session: Session = Depends(get_db_session),
):
    gaps = discover_missing_agreement_gaps(
        session=session, min_cluster_hits=min_cluster_hits
    )
    session.commit()
    return {"discovered": len(gaps)}


@app.get("/agreement-gaps")
def agreement_gaps(
    status: GapStatus | None = None,
    session: Session = Depends(get_db_session),
):
    gaps = list_agreement_gaps(session=session, status=status)
    return [
        {
            "id": gap.id,
            "gap_key": gap.gap_key,
            "buyer_name": gap.buyer_name,
            "status": gap.status.value,
            "confidence": gap.confidence,
            "rationale": gap.rationale,
            "evidence": gap.evidence_json,
            "note": gap.note,
        }
        for gap in gaps
    ]


@app.patch("/agreement-gaps/{gap_id}/status")
def update_agreement_gap_status(
    gap_id: int,
    update: GapStatusUpdate,
    session: Session = Depends(get_db_session),
):
    try:
        gap = set_gap_status(
            session=session,
            gap_id=gap_id,
            status=update.status,
            actor=update.actor,
            note=update.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return {"id": gap.id, "status": gap.status.value}
