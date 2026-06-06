from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from job_scraper.kois.db import Base
from job_scraper.kois import schema  # noqa: F401

INIT_MIGRATION_ID = "20260605_kois_phase1_init"
DROP_CONTENT_HASH_UNIQUE_MIGRATION_ID = "20260606_drop_raw_source_content_hash_unique"


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


MIGRATIONS: list[tuple[str, Callable]] = [
    (INIT_MIGRATION_ID, _run_init),
    (DROP_CONTENT_HASH_UNIQUE_MIGRATION_ID, _drop_content_hash_unique),
]


def run_migrations(engine: Engine) -> None:
    with engine.begin() as connection:
        _ensure_migrations_table(connection)
        for migration_id, migration_fn in MIGRATIONS:
            if _is_applied(connection, migration_id):
                continue
            migration_fn(connection)
            _mark_applied(connection, migration_id)
