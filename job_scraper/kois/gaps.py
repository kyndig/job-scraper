from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_scraper.kois.repository import upsert_agreement_gap
from job_scraper.kois.schema import (
    AgreementGap,
    AgreementSignal,
    GapStatus,
    OpportunityCluster,
)
from job_scraper.kois.utils import normalize_text


def discover_missing_agreement_gaps(
    session: Session, min_cluster_hits: int = 2
) -> list[AgreementGap]:
    buyers_with_agreements = {
        normalize_text(buyer)
        for buyer in session.execute(
            select(AgreementSignal.buyer_name).where(AgreementSignal.buyer_name.is_not(None))
        ).scalars()
        if normalize_text(buyer)
    }

    clusters_by_buyer: dict[str, list[OpportunityCluster]] = defaultdict(list)
    for cluster in session.execute(
        select(OpportunityCluster).where(OpportunityCluster.customer.is_not(None))
    ).scalars():
        buyer_key = normalize_text(cluster.customer)
        if not buyer_key:
            continue
        clusters_by_buyer[buyer_key].append(cluster)

    persisted: list[AgreementGap] = []
    existing_gaps_by_buyer: dict[str, list[AgreementGap]] = defaultdict(list)
    for gap in session.execute(select(AgreementGap)).scalars():
        buyer_key = normalize_text(gap.buyer_name)
        if buyer_key:
            existing_gaps_by_buyer[buyer_key].append(gap)

    for buyer_key, clusters in clusters_by_buyer.items():
        if buyer_key in buyers_with_agreements:
            for gap in existing_gaps_by_buyer.get(buyer_key, []):
                if gap.status not in {GapStatus.OPEN, GapStatus.ACKNOWLEDGED}:
                    continue
                gap.status = GapStatus.IGNORED
                gap.note = (
                    "Auto-closed after matching agreement signal detected for this buyer."
                )
                session.flush()
                persisted.append(gap)
            continue
        if len(clusters) < min_cluster_hits:
            continue

        buyer_name = clusters[0].customer or buyer_key
        payload = {
            "gap_key": f"buyer:{buyer_key}",
            "buyer_name": buyer_name,
            "status": GapStatus.OPEN,
            "confidence": min(0.99, 0.55 + 0.1 * len(clusters)),
            "rationale": "Repeated buyer demand without matching DPS/frame agreement signal.",
            "evidence_json": {
                "cluster_ids": [cluster.id for cluster in clusters],
                "cluster_count": len(clusters),
            },
        }
        persisted.append(upsert_agreement_gap(session, payload))
    return persisted


def set_gap_status(
    session: Session,
    gap_id: int,
    status: GapStatus,
    actor: str = "reviewer",
    note: str | None = None,
) -> AgreementGap:
    gap = session.get(AgreementGap, gap_id)
    if not gap:
        raise ValueError(f"Agreement gap {gap_id} not found")
    gap.status = status
    gap.note = note
    session.flush()
    return gap
