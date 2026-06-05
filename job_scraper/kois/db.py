from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from job_scraper.kois.config import get_settings

Base = declarative_base()


def create_db_engine():
    settings = get_settings()
    return create_engine(settings.database_url, future=True)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=create_db_engine(),
    future=True,
    expire_on_commit=False,
)


def get_db_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
