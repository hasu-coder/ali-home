from __future__ import annotations

import httpx
from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI, AuthenticationError, RateLimitError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.llm.openai_provider import LLMProviderError
from app.llm.provider import LLMProvider, LLMResponse


class HetznerProvider(LLMProvider):
    """Qwen through Hetzner's OpenAI-compatible Chat Completions API.

    This provider is deliberately text-only. It never sends a request to
    OpenAI and it does not claim to have web-search, speech or Realtime tools.
    """

    def __init__(self, settings: Settings, db: Session):
        self.settings = settings
        self.db = db
        self.client = (
            AsyncOpenAI(
                base_url=settings.hetzner_inference_base_url.rstrip("/"),
                api_key=settings.hetzner_inference_api_key,
            )
            if settings.hetzner_inference_api_key
            else None
        )

    async def complete(self, messages: list[dict[str, str]]) -> LLMResponse:
        if not self.client:
            raise LLMProviderError("hetzner_not_configured")

        try:
            result = await self.client.chat.completions.create(
                model=self.settings.hetzner_inference_model,
                messages=messages,
                max_tokens=self.settings.openai_max_output_tokens,
                timeout=20,
            )
        except (
            APITimeoutError,
            APIConnectionError,
            RateLimitError,
            AuthenticationError,
            APIError,
            httpx.HTTPError,
        ) as exc:
            raise LLMProviderError(f"hetzner_{exc.__class__.__name__}") from exc

        text = result.choices[0].message.content if result.choices else ""
        if not isinstance(text, str) or not text.strip():
            raise LLMProviderError("hetzner_empty_response")

        usage = result.usage
        return LLMResponse(
            text=text.strip(),
            provider="hetzner",
            model=self.settings.hetzner_inference_model,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            estimated_cost=0.0,
            used_remote_model=True,
        )
