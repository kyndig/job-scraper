from sqlalchemy import text
from sqlalchemy.engine import Engine

from job_scraper.kois.db import Base
from job_scraper.kois import schema  # noqa: F401

MIGRATION_ID = "20260605_kois_phase1_init"


def run_migrations(engine: Engine) -> None:
    with engine.begin() as connection:
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
        applied = connection.execute(
            text(
                "SELECT migration_id FROM kois_schema_migrations WHERE migration_id = :migration_id"
            ),
            {"migration_id": MIGRATION_ID},
        ).first()
        if applied:
            return

        Base.metadata.create_all(bind=connection)
        connection.execute(
            text(
                "INSERT INTO kois_schema_migrations (migration_id) VALUES (:migration_id)"
            ),
            {"migration_id": MIGRATION_ID},
        )
