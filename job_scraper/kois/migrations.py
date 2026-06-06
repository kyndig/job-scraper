from collections.abc import Callable

from sqlalchemy import inspect
from sqlalchemy import text
from sqlalchemy.engine import Engine

from job_scraper.kois.db import Base
from job_scraper.kois import schema  # noqa: F401

INIT_MIGRATION_ID = "20260605_kois_phase1_init"
DROP_CONTENT_HASH_UNIQUE_MIGRATION_ID = "20260606_drop_raw_source_content_hash_unique"
PHASE2_INTELLIGENCE_MIGRATION_ID = "20260606_phase2_agreements_and_gaps"
PHASE3_SALES_FILTERING_MIGRATION_ID = "20260607_phase3_sales_filtering"


def _ensure_migrations_table(connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS kois_schema_migrations (
                migration_id TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )


def _is_applied(connection, migration_id: str) -> bool:
    return (
        connection.execute(
            text(
                "SELECT migration_id FROM kois_schema_migrations WHERE migration_id = :migration_id"
            ),
            {"migration_id": migration_id},
        ).first()
        is not None
    )


def _mark_applied(connection, migration_id: str) -> None:
    connection.execute(
        text("INSERT INTO kois_schema_migrations (migration_id) VALUES (:migration_id)"),
        {"migration_id": migration_id},
    )


def _run_init(connection) -> None:
    Base.metadata.create_all(bind=connection)


def _drop_content_hash_unique(connection) -> None:
    connection.execute(
        text(
            "ALTER TABLE raw_source_items DROP CONSTRAINT IF EXISTS uq_raw_source_content_hash"
        )
    )


def _add_phase2_tables(connection) -> None:
    schema.AgreementSignal.__table__.create(bind=connection, checkfirst=True)
    schema.AgreementGap.__table__.create(bind=connection, checkfirst=True)


def _add_phase3_cluster_filtering_fields(connection) -> None:
    inspector = inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("opportunity_clusters")}
    if "role_category" not in columns:
        connection.execute(
            text("ALTER TABLE opportunity_clusters ADD COLUMN role_category VARCHAR(128)")
        )
    if "role_tags" not in columns:
        connection.execute(
            text("ALTER TABLE opportunity_clusters ADD COLUMN role_tags JSON")
        )
        connection.execute(
            text(
                "UPDATE opportunity_clusters SET role_tags = '[]' WHERE role_tags IS NULL"
            )
        )
    if "relevance_score" not in columns:
        connection.execute(
            text(
                "ALTER TABLE opportunity_clusters ADD COLUMN relevance_score FLOAT DEFAULT 0"
            )
        )
        connection.execute(
            text(
                "UPDATE opportunity_clusters "
                "SET relevance_score = 0 WHERE relevance_score IS NULL"
            )
        )
    if "relevance_rationale" not in columns:
        connection.execute(
            text("ALTER TABLE opportunity_clusters ADD COLUMN relevance_rationale TEXT")
        )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_opportunity_clusters_role_category "
            "ON opportunity_clusters (role_category)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_opportunity_clusters_relevance_score "
            "ON opportunity_clusters (relevance_score)"
        )
    )


MIGRATIONS: list[tuple[str, Callable]] = [
    (INIT_MIGRATION_ID, _run_init),
    (DROP_CONTENT_HASH_UNIQUE_MIGRATION_ID, _drop_content_hash_unique),
    (PHASE2_INTELLIGENCE_MIGRATION_ID, _add_phase2_tables),
    (PHASE3_SALES_FILTERING_MIGRATION_ID, _add_phase3_cluster_filtering_fields),
]


def run_migrations(engine: Engine) -> None:
    with engine.begin() as connection:
        _ensure_migrations_table(connection)
        for migration_id, migration_fn in MIGRATIONS:
            if _is_applied(connection, migration_id):
                continue
            migration_fn(connection)
            _mark_applied(connection, migration_id)
