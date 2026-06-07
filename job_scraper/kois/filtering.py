from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from job_scraper.kois.config import KOISSettings
from job_scraper.kois.schema import OpportunityCluster, ReviewStatus
from job_scraper.kois.utils import normalize_text


DEFAULT_ROLE_TAXONOMY: dict[str, list[str]] = {
    "data_engineering": [
        "data engineer",
        "data platform",
        "etl",
        "airflow",
        "spark",
        "dbt",
        "pipeline",
        "databricks",
    ],
    "backend": [
        "backend",
        "api",
        "python",
        "java",
        "golang",
        "microservice",
        "fastapi",
        "django",
        "spring",
    ],
    "frontend": [
        "frontend",
        "react",
        "typescript",
        "javascript",
        "angular",
        "vue",
        "ui",
    ],
    "cloud_devops": [
        "devops",
        "platform engineer",
        "kubernetes",
        "terraform",
        "aws",
        "azure",
        "gcp",
        "ci/cd",
    ],
    "security": [
        "security",
        "iam",
        "soc",
        "siem",
        "zero trust",
        "risk",
        "compliance",
    ],
    "project_management": [
        "project manager",
        "scrum master",
        "delivery lead",
        "program manager",
    ],
    "qa_test": [
        "qa",
        "test automation",
        "selenium",
        "cypress",
        "quality assurance",
    ],
}


@dataclass(frozen=True)
class ClusterFilteringResult:
    role_category: str | None
    role_tags: list[str]
    relevance_score: float
    relevance_rationale: str


class OpportunityFilterPolicy:
    def __init__(self, settings: KOISSettings):
        self.settings = settings
        taxonomy = getattr(settings, "role_taxonomy", None)
        availability = getattr(settings, "availability_profile", None)
        self.role_taxonomy = taxonomy or DEFAULT_ROLE_TAXONOMY
        self.availability_profile = availability or {}
        self.digest_mode = normalize_text(getattr(settings, "digest_mode", "balanced")) or "balanced"
        self.min_relevance = float(getattr(settings, "digest_min_relevance_score", 0.35))
        self.min_confidence = float(
            getattr(settings, "digest_min_source_confidence", 0.75)
        )

    def evaluate_cluster(self, cluster: OpportunityCluster) -> ClusterFilteringResult:
        role_category, role_tags = self._classify_cluster(cluster)
        relevance_score, rationale = self._score_relevance(cluster, role_category)
        return ClusterFilteringResult(
            role_category=role_category,
            role_tags=role_tags,
            relevance_score=relevance_score,
            relevance_rationale=rationale,
        )

    def apply_to_cluster(self, cluster: OpportunityCluster) -> ClusterFilteringResult:
        result = self.evaluate_cluster(cluster)
        cluster.role_category = result.role_category
        cluster.role_tags_json = result.role_tags
        cluster.relevance_score = result.relevance_score
        cluster.relevance_rationale = result.relevance_rationale
        return result

    def should_include_digest(
        self,
        cluster: OpportunityCluster,
        *,
        evaluated_relevance: float | None = None,
        min_relevance_override: float | None = None,
    ) -> bool:
        if cluster.review_status in (ReviewStatus.IGNORED, ReviewStatus.WATCH_ONLY):
            return False
        if (
            cluster.review_status == ReviewStatus.NEEDS_REVIEW
            and cluster.confidence < self.min_confidence
        ):
            return False
        relevance = (
            evaluated_relevance
            if evaluated_relevance is not None
            else cluster.relevance_score
        )
        threshold = (
            min_relevance_override
            if min_relevance_override is not None
            else self.min_relevance
        )
        return relevance >= threshold

    def _classify_cluster(self, cluster: OpportunityCluster) -> tuple[str | None, list[str]]:
        haystack_parts = [cluster.title, cluster.customer]
        for source in cluster.sources:
            record = source.record
            haystack_parts.extend(
                [
                    record.title,
                    record.summary,
                    record.description,
                    record.broker,
                    record.source_url,
                ]
            )
        haystack = normalize_text(" ".join(part or "" for part in haystack_parts))
        if not haystack:
            return None, []

        scores: dict[str, int] = {}
        for role, keywords in self.role_taxonomy.items():
            score = 0
            for keyword in keywords:
                normalized = normalize_text(keyword)
                if normalized and normalized in haystack:
                    score += 1
            if score:
                scores[role] = score

        if not scores:
            return "generalist", []
        ranked = sorted(scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
        role_tags = [role for role, _ in ranked[:3]]
        return ranked[0][0], role_tags

    def _score_relevance(
        self, cluster: OpportunityCluster, role_category: str | None
    ) -> tuple[float, str]:
        confidence_component = min(max(cluster.confidence, 0.0), 1.0) * 0.5
        role_component = 0.2
        capacity_component = 0.0
        notes = [f"confidence={cluster.confidence:.2f}"]

        if role_category and role_category in self.availability_profile:
            capacity = self.availability_profile[role_category]
            if capacity > 0:
                capacity_component = min(0.4, 0.1 + (capacity * 0.06))
                notes.append(f"capacity={capacity}")
            else:
                capacity_component = -0.2
                notes.append("capacity=0")
        elif self.availability_profile:
            role_component = 0.0
            capacity_component = -0.2
            notes.append("role_not_in_capacity_profile")
        else:
            notes.append("availability_profile=empty")

        if self.digest_mode == "high_precision":
            score = confidence_component + role_component + capacity_component - 0.15
            notes.append("mode=high_precision")
        elif self.digest_mode == "high_recall":
            score = confidence_component + role_component + capacity_component + 0.1
            notes.append("mode=high_recall")
        else:
            score = confidence_component + role_component + capacity_component
            notes.append("mode=balanced")

        bounded_score = max(0.0, min(1.0, score))
        return bounded_score, ", ".join(notes)


def score_clusters(
    session: Session, clusters: list[OpportunityCluster], settings: KOISSettings
) -> dict[int, ClusterFilteringResult]:
    policy = OpportunityFilterPolicy(settings)
    results: dict[int, ClusterFilteringResult] = {}
    unique_clusters = {cluster.id: cluster for cluster in clusters}.values()
    for cluster in unique_clusters:
        results[cluster.id] = policy.apply_to_cluster(cluster)
    session.flush()
    return results
