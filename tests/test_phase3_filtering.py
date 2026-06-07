import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from job_scraper.kois import review_api
from job_scraper.kois.config import KOISSettings
from job_scraper.kois.filtering import OpportunityFilterPolicy, score_clusters
from job_scraper.kois.repository import attach_cluster_source, create_extracted_record, create_or_update_cluster, upsert_raw_source_item
from job_scraper.kois.schema import Base, ReviewStatus
from job_scraper.kois.domain import RawIngestionItem


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(bind=engine, future=True)


def _make_cluster(
    session: Session,
    *,
    title: str,
    confidence: float = 0.95,
    description: str | None = None,
):
    if description is None:
        if "project manager" in title.lower():
            description = "Need a senior project manager to lead delivery and stakeholder coordination."
        else:
            description = "Need strong data engineer with dbt and airflow."
    raw = upsert_raw_source_item(
        session,
        RawIngestionItem(
            source_type="scraper",
            source_name="mercell",
            external_id=f"id-{title}",
            raw_body="raw-data",
        ),
    )
    record = create_extracted_record(
        session,
        {
            "raw_source_item_id": raw.id,
            "title": title,
            "customer": "Kynd",
            "broker": "mercell",
            "source_url": f"https://example.com/{raw.id}",
            "deadline": "2026-06-30",
            "description": description,
            "summary": None,
            "extracted_data": {},
            "extraction_confidence": 0.95,
        },
    )
    cluster = create_or_update_cluster(
        session=session,
        cluster_key=f"https://example.com/{raw.id}",
        title=title,
        customer="Kynd",
        confidence=confidence,
        review_status=ReviewStatus.AUTO_ACCEPTED,
    )
    attach_cluster_source(session, cluster, record, 0.95, "url")
    cluster.primary_source_record_id = record.id
    session.flush()
    return cluster


def test_phase3_policy_classifies_and_scores():
    session = _session()
    cluster = _make_cluster(session, title="Senior Data Engineer")
    settings = KOISSettings(availability_profile_json='{"data_engineering": 2}')
    policy = OpportunityFilterPolicy(settings)
    result = policy.apply_to_cluster(cluster)
    session.commit()

    assert result.role_category == "data_engineering"
    assert cluster.relevance_score > 0.5
    assert policy.should_include_digest(cluster)


def test_phase3_policy_blocks_low_confidence_needs_review():
    session = _session()
    cluster = _make_cluster(session, title="Senior Data Engineer", confidence=0.6)
    cluster.review_status = ReviewStatus.NEEDS_REVIEW
    settings = KOISSettings(
        availability_profile_json='{"data_engineering": 3}',
        digest_min_source_confidence=0.75,
    )
    policy = OpportunityFilterPolicy(settings)
    policy.apply_to_cluster(cluster)

    assert policy.should_include_digest(cluster) is False


def test_score_clusters_persists_phase3_fields():
    session = _session()
    cluster = _make_cluster(session, title="Backend Developer")
    settings = KOISSettings(availability_profile_json='{"backend": 1}')
    score_clusters(session, [cluster], settings)
    session.commit()

    assert cluster.role_category is not None
    assert isinstance(cluster.role_tags_json, list)
    assert cluster.relevance_rationale is not None


def test_relevant_opportunities_endpoint_uses_shared_policy(monkeypatch):
    session = _session()
    relevant_cluster = _make_cluster(session, title="Senior Data Engineer")
    irrelevant_cluster = _make_cluster(session, title="Project Manager")
    irrelevant_cluster.relevance_score = 0.0
    session.commit()

    settings = KOISSettings(
        availability_profile_json='{"data_engineering": 2}',
        digest_min_relevance_score=0.45,
    )
    monkeypatch.setattr(review_api, "get_settings", lambda: settings)

    response = review_api.relevant_opportunities(session=session, limit=50)
    returned_ids = {item["id"] for item in response}

    assert relevant_cluster.id in returned_ids
    assert irrelevant_cluster.id not in returned_ids


def test_relevant_opportunities_filters_role_on_fresh_evaluation(monkeypatch):
    session = _session()
    cluster = _make_cluster(session, title="Senior Data Engineer")
    cluster.role_category = "backend"
    session.commit()

    settings = KOISSettings(
        availability_profile_json='{"data_engineering": 2}',
        digest_min_relevance_score=0.45,
    )
    monkeypatch.setattr(review_api, "get_settings", lambda: settings)

    response = review_api.relevant_opportunities(
        session=session, role="data_engineering", limit=10
    )

    assert len(response) == 1
    assert response[0]["id"] == cluster.id
    assert response[0]["role_category"] == "data_engineering"


def test_relevant_opportunities_honors_query_min_relevance_override(monkeypatch):
    session = _session()
    cluster = _make_cluster(session, title="Senior Data Engineer")
    session.commit()

    settings = KOISSettings(
        availability_profile_json='{"data_engineering": 1}',
        digest_min_relevance_score=0.9,
    )
    monkeypatch.setattr(review_api, "get_settings", lambda: settings)

    response = review_api.relevant_opportunities(
        session=session, min_relevance_score=0.5, limit=10
    )
    returned_ids = {item["id"] for item in response}

    assert cluster.id in returned_ids


def test_relevant_opportunities_limit_applies_after_fresh_relevance_sort(monkeypatch):
    session = _session()
    stale_high = _make_cluster(session, title="Project Manager")
    fresh_high = _make_cluster(session, title="Senior Data Engineer")
    stale_high.relevance_score = 0.99
    fresh_high.relevance_score = 0.01
    session.commit()

    settings = KOISSettings(
        availability_profile_json='{"data_engineering": 2}',
        digest_min_relevance_score=0.45,
    )
    monkeypatch.setattr(review_api, "get_settings", lambda: settings)

    response = review_api.relevant_opportunities(session=session, limit=1)

    assert len(response) == 1
    assert response[0]["id"] == fresh_high.id


def test_role_classification_uses_word_boundaries_for_keywords():
    session = _session()
    cluster = _make_cluster(
        session,
        title="Frontend JavaScript Developer",
        description="Need a frontend specialist with javascript and react experience.",
    )
    settings = KOISSettings()
    policy = OpportunityFilterPolicy(settings)

    result = policy.evaluate_cluster(cluster)

    assert result.role_category == "frontend"
    assert "backend" not in result.role_tags


def test_invalid_availability_profile_json_raises():
    settings = KOISSettings(availability_profile_json="not-json")
    with pytest.raises(ValueError):
        _ = settings.availability_profile


def test_availability_profile_rejects_boolean_capacity_values():
    settings = KOISSettings(availability_profile_json='{"data_engineering": true}')
    with pytest.raises(
        ValueError, match="must be an integer capacity value"
    ):
        _ = settings.availability_profile


def test_list_clusters_filters_role_and_relevance_on_fresh_evaluation(monkeypatch):
    session = _session()
    cluster = _make_cluster(session, title="Senior Data Engineer")
    cluster.role_category = "backend"
    cluster.relevance_score = 0.0
    session.commit()

    settings = KOISSettings(
        availability_profile_json='{"data_engineering": 2}',
        digest_min_relevance_score=0.45,
    )
    monkeypatch.setattr(review_api, "get_settings", lambda: settings)

    response = review_api.list_clusters(
        session=session,
        role="data_engineering",
        min_relevance_score=0.5,
    )

    assert len(response) == 1
    assert response[0]["id"] == cluster.id
    assert response[0]["role_category"] == "data_engineering"
    assert response[0]["relevance_score"] >= 0.5
