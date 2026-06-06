from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from job_scraper.kois.digest import send_digest_items
from job_scraper.kois.repository import create_digest_item, create_or_update_cluster
from job_scraper.kois.schema import Base, DigestItem, ReviewStatus
from job_scraper.slack_poster import SlackPoster


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(bind=engine, future=True)


def test_ignored_cluster_clears_unsent_digest_items():
    session = _session()
    cluster = create_or_update_cluster(
        session=session,
        cluster_key="cluster-ignored-pending",
        title="Ignore this",
        customer="Kynd",
        confidence=0.9,
        review_status=ReviewStatus.IGNORED,
    )
    create_digest_item(
        session=session,
        cluster=cluster,
        status=ReviewStatus.IGNORED,
        payload={"cluster_id": cluster.id, "review_status": ReviewStatus.IGNORED.value},
    )
    session.commit()

    sent = send_digest_items(
        session=session,
        clusters=[cluster],
        slack=SlackPoster(optional=True),
        live_posting=False,
        channel="job-posting",
    )
    session.commit()

    unsent = session.execute(
        select(DigestItem).where(
            DigestItem.opportunity_cluster_id == cluster.id,
            DigestItem.sent_at.is_(None),
        )
    ).scalars().all()

    assert sent == []
    assert unsent == []
