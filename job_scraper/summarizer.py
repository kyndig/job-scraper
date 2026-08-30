from __future__ import annotations

import logging
from typing import Protocol

from job_scraper.kois.config import KOISSettings

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """
Your job is to summarize job descriptions and make it easy to understand the requirements of the job and what it is about.
You will make bullet points when listing out requirements, and will format the summary in a nice and simple manner.
Make the summary in the same language as the job description. If it is in Norwegian the summary is in Norwegian, and
if it's in English then the summary is in English.
Keep the summary under 1500 characters.

Use markdown for Slack as the formatting for the summary. Use one * instead of two when doing bold headlines.
""".strip()


class _CompletionClient(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...


class _AnthropicClient:
    def __init__(self, api_key: str, model: str) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, *, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        texts = [
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text" and getattr(block, "text", None)
        ]
        return "\n".join(texts).strip()


class _KimiClient:
    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def complete(self, *, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        choice = response.choices[0].message.content if response.choices else None
        return (choice or "").strip()


class JobDescriptionSummarizer:
    system_instruction: str = SYSTEM_INSTRUCTION

    def __init__(
        self,
        client: _CompletionClient | None = None,
        *,
        optional: bool = False,
    ) -> None:
        self.client = client
        if self.client is None and not optional:
            raise ValueError(
                "No LLM configured. Set KOIS_LLM_PROVIDER to anthropic or kimi "
                "and the matching API key."
            )

    @classmethod
    def from_settings(
        cls, settings: KOISSettings, *, optional: bool = True
    ) -> JobDescriptionSummarizer:
        resolver = getattr(settings, "resolved_llm_provider", None)
        provider = resolver() if callable(resolver) else None
        if provider is None:
            return cls(client=None, optional=optional)
        if provider == "anthropic":
            return cls(
                client=_AnthropicClient(
                    api_key=getattr(settings, "anthropic_api_key", None) or "",
                    model=getattr(settings, "anthropic_model", "claude-sonnet-4-5"),
                ),
                optional=optional,
            )
        return cls(
            client=_KimiClient(
                api_key=getattr(settings, "kimi_api_key", None) or "",
                model=getattr(settings, "kimi_model", "kimi-k2-turbo-preview"),
                base_url=getattr(
                    settings, "kimi_base_url", "https://api.moonshot.ai/v1"
                ),
            ),
            optional=optional,
        )

    def summarize(self, description: str) -> str | None:
        if self.client is None:
            return None
        try:
            return self.client.complete(
                system=self.system_instruction,
                user=description,
            ) or None
        except Exception:
            logger.exception("LLM summarization failed")
            return None
