from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KOISSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/kois"
    )

    slack_token: str | None = Field(default=None, alias="SLACK_TOKEN")
    slack_channel: str = "job-posting"

    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")

    imap_host: str | None = None
    imap_port: int = 993
    imap_username: str | None = None
    imap_password: str | None = None
    imap_mailbox: str = "INBOX"
    imap_since_uid: int = 1
    imap_source_name: str = "oppdrag@kynd.no"

    run_live_slack: bool = False


@lru_cache(maxsize=1)
def get_settings() -> KOISSettings:
    return KOISSettings()
