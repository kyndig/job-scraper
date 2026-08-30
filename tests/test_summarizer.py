import pytest

from job_scraper.kois.config import KOISSettings
from job_scraper.summarizer import JobDescriptionSummarizer


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    for key in (
        "KOIS_LLM_PROVIDER",
        "ANTHROPIC_API_KEY",
        "KIMI_API_KEY",
        "MOONSHOT_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return f"summary:{user[:20]}"


def test_optional_summarizer_without_keys_returns_none():
    settings = KOISSettings(_env_file=None)
    summarizer = JobDescriptionSummarizer.from_settings(settings, optional=True)
    assert summarizer.summarize("Need a data engineer") is None


def test_explicit_anthropic_provider():
    settings = KOISSettings(
        _env_file=None,
        llm_provider="anthropic",
        anthropic_api_key="sk-ant-test",
    )
    assert settings.resolved_llm_provider() == "anthropic"


def test_explicit_kimi_provider_accepts_moonshot_alias(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-kimi-test")
    settings = KOISSettings(_env_file=None, llm_provider="kimi")
    assert settings.resolved_llm_provider() == "kimi"
    assert settings.kimi_api_key == "sk-kimi-test"


def test_auto_selects_single_key():
    settings = KOISSettings(_env_file=None, anthropic_api_key="sk-ant-test")
    assert settings.resolved_llm_provider() == "anthropic"


def test_both_keys_require_explicit_provider():
    settings = KOISSettings(
        _env_file=None,
        anthropic_api_key="sk-ant-test",
        kimi_api_key="sk-kimi-test",
    )
    try:
        settings.resolved_llm_provider()
        raised = False
    except ValueError as exc:
        raised = True
        assert "KOIS_LLM_PROVIDER" in str(exc)
    assert raised


def test_summarize_uses_injected_client():
    client = FakeClient()
    summarizer = JobDescriptionSummarizer(client=client)
    assert summarizer.summarize("Oppdrag: backend") == "summary:Oppdrag: backend"
    assert client.calls[0][1] == "Oppdrag: backend"


def test_invalid_provider_rejected():
    settings = KOISSettings(_env_file=None, llm_provider="gemini")
    try:
        settings.resolved_llm_provider()
        raised = False
    except ValueError:
        raised = True
    assert raised
