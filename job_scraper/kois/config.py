from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property, lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class ImapAccount:
    host: str
    username: str
    password: str
    mailbox: str = "INBOX"
    source_name: str = "oppdrag@kynd.no"
    port: int = 993
    since_uid: int = 1


class KOISSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/kois"
    )

    slack_token: str | None = Field(default=None, alias="SLACK_TOKEN")
    slack_channel: str = "job-posting"

    llm_provider: str | None = Field(default=None, alias="KOIS_LLM_PROVIDER")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-5", alias="ANTHROPIC_MODEL")
    kimi_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("KIMI_API_KEY", "MOONSHOT_API_KEY"),
    )
    kimi_base_url: str = Field(
        default="https://api.moonshot.ai/v1", alias="KIMI_BASE_URL"
    )
    kimi_model: str = Field(default="kimi-k2-turbo-preview", alias="KIMI_MODEL")

    imap_host: str | None = None
    imap_port: int = 993
    imap_username: str | None = None
    imap_password: str | None = None
    imap_mailbox: str = "INBOX"
    imap_since_uid: int = 1
    imap_source_name: str = "oppdrag@kynd.no"
    imap_accounts_json: str | None = None

    skip_scrapers: bool = Field(default=False, alias="KOIS_SKIP_SCRAPERS")
    review_token: str | None = Field(default=None, alias="KOIS_REVIEW_TOKEN")

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
    def imap_accounts(self) -> list[ImapAccount]:
        if self.imap_accounts_json:
            return _parse_imap_accounts_json(self.imap_accounts_json)
        if self.imap_host and self.imap_username and self.imap_password:
            return [
                ImapAccount(
                    host=self.imap_host,
                    username=self.imap_username,
                    password=self.imap_password,
                    mailbox=self.imap_mailbox,
                    source_name=self.imap_source_name,
                    port=self.imap_port,
                    since_uid=self.imap_since_uid,
                )
            ]
        return []

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

    def resolved_llm_provider(self) -> str | None:
        explicit = _normalize_provider(self.llm_provider)
        has_anthropic = bool(self.anthropic_api_key)
        has_kimi = bool(self.kimi_api_key)
        if explicit:
            if explicit not in {"anthropic", "kimi"}:
                raise ValueError(
                    "KOIS_LLM_PROVIDER must be 'anthropic' or 'kimi'."
                )
            if explicit == "anthropic" and not has_anthropic:
                raise ValueError(
                    "ANTHROPIC_API_KEY is required when KOIS_LLM_PROVIDER=anthropic."
                )
            if explicit == "kimi" and not has_kimi:
                raise ValueError(
                    "KIMI_API_KEY (or MOONSHOT_API_KEY) is required when "
                    "KOIS_LLM_PROVIDER=kimi."
                )
            return explicit
        if has_anthropic and has_kimi:
            raise ValueError(
                "Both Anthropic and Kimi API keys are set. Set KOIS_LLM_PROVIDER "
                "to 'anthropic' or 'kimi'."
            )
        if has_anthropic:
            return "anthropic"
        if has_kimi:
            return "kimi"
        return None



@lru_cache(maxsize=1)
def get_settings() -> KOISSettings:
    return KOISSettings()


def _parse_imap_accounts_json(raw_value: str) -> list[ImapAccount]:
    try:
        decoded = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"imap_accounts_json must be valid JSON: {exc}") from exc
    if not isinstance(decoded, list):
        raise TypeError("imap_accounts_json must decode to an array of objects.")
    accounts: list[ImapAccount] = []
    for index, item in enumerate(decoded):
        if not isinstance(item, dict):
            raise TypeError(f"imap_accounts_json[{index}] must be an object.")
        host = item.get("host")
        username = item.get("username")
        password = item.get("password")
        if not host or not username or not password:
            raise ValueError(
                f"imap_accounts_json[{index}] requires host, username, and password."
            )
        if not isinstance(host, str) or not isinstance(username, str) or not isinstance(password, str):
            raise TypeError(
                f"imap_accounts_json[{index}] host, username, and password must be strings."
            )
        mailbox = item.get("mailbox", "INBOX")
        source_name = item.get("source_name", username)
        port = item.get("port", 993)
        since_uid = item.get("since_uid", 1)
        if not isinstance(mailbox, str) or not isinstance(source_name, str):
            raise TypeError(
                f"imap_accounts_json[{index}] mailbox and source_name must be strings."
            )
        if not isinstance(port, int) or isinstance(port, bool):
            raise TypeError(f"imap_accounts_json[{index}] port must be an integer.")
        if not isinstance(since_uid, int) or isinstance(since_uid, bool) or since_uid < 1:
            raise ValueError(
                f"imap_accounts_json[{index}] since_uid must be an integer >= 1."
            )
        accounts.append(
            ImapAccount(
                host=host,
                username=username,
                password=password,
                mailbox=mailbox,
                source_name=source_name,
                port=port,
                since_uid=since_uid,
            )
        )
    return accounts


def _parse_int_mapping_json(raw_value: str, *, field_name: str) -> dict[str, int]:
    try:
        decoded = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to an object.")
    parsed: dict[str, int] = {}
    for key, value in decoded.items():
        if not isinstance(key, str):
            raise TypeError(f"{field_name} keys must be strings.")
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(
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
        raise TypeError("role_taxonomy_json must decode to an object.")
    parsed: dict[str, list[str]] = {}
    for key, value in decoded.items():
        if not isinstance(key, str):
            raise TypeError("role_taxonomy_json keys must be strings.")
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise TypeError(
                f"role_taxonomy_json[{key!r}] must be an array of strings."
            )
        parsed[key.strip().lower()] = [item.strip().lower() for item in value if item.strip()]
    return parsed


def _normalize_provider(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lower() or None

