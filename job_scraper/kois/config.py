from __future__ import annotations

import json
from functools import cached_property
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

    doffin_feed_url: str | None = None
    doffin_feed_json: str | None = None
    procurement_feed_urls_by_source: dict[str, str] = Field(default_factory=dict)
    procurement_feed_json_by_source: dict[str, str] = Field(default_factory=dict)
    agreement_gap_min_cluster_hits: int = 2

    digest_mode: str = "balanced"
    digest_min_relevance_score: float = 0.35
    digest_min_source_confidence: float = 0.75
    digest_cadence_minutes: int = 0
    availability_profile_json: str | None = None
    role_taxonomy_json: str | None = None

    run_live_slack: bool = False

    @cached_property
    def availability_profile(self) -> dict[str, int]:
        if not self.availability_profile_json:
            return {}
        return _parse_int_mapping_json(
            self.availability_profile_json, field_name="availability_profile_json"
        )

    @cached_property
    def role_taxonomy(self) -> dict[str, list[str]]:
        if not self.role_taxonomy_json:
            return {}
        return _parse_role_taxonomy_json(self.role_taxonomy_json)


@lru_cache(maxsize=1)
def get_settings() -> KOISSettings:
    return KOISSettings()


def _parse_int_mapping_json(raw_value: str, *, field_name: str) -> dict[str, int]:
    try:
        decoded = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{field_name} must decode to an object.")
    parsed: dict[str, int] = {}
    for key, value in decoded.items():
        if not isinstance(key, str):
            raise ValueError(f"{field_name} keys must be strings.")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"{field_name}[{key!r}] must be an integer capacity value."
            )
        parsed[key.strip().lower()] = value
    return parsed


def _parse_role_taxonomy_json(raw_value: str) -> dict[str, list[str]]:
    try:
        decoded = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"role_taxonomy_json must be valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ValueError("role_taxonomy_json must decode to an object.")
    parsed: dict[str, list[str]] = {}
    for key, value in decoded.items():
        if not isinstance(key, str):
            raise ValueError("role_taxonomy_json keys must be strings.")
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(
                f"role_taxonomy_json[{key!r}] must be an array of strings."
            )
        parsed[key.strip().lower()] = [item.strip().lower() for item in value if item.strip()]
    return parsed
