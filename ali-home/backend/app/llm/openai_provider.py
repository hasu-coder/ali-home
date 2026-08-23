import uuid
from datetime import datetime, timedelta, timezone

import httpx
from openai import AsyncOpenAI
from openai import APIConnectionError, APIError, APITimeoutError, AuthenticationError, RateLimitError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.llm.provider import LLMProvider, LLMResponse
from app.models.entities import OpenAIUsage


class BudgetExceededError(RuntimeError):
    pass


class LLMProviderError(RuntimeError):
    pass


class OpenAIProvider(LLMProvider):
    def __init__(self, settings: Settings, db: Session):
        self.settings = settings
        self.db = db
        self.client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self.settings.openai_input_cost_per_1m / 1_000_000
            + completion_tokens * self.settings.openai_output_cost_per_1m / 1_000_000
        )

    def _spent_since(self, start: datetime) -> float:
        value = self.db.query(func.coalesce(func.sum(OpenAIUsage.estimated_cost), 0.0)).filter(
            OpenAIUsage.created_at >= start
        ).scalar()
        return float(value or 0.0)

    def _check_budget(self) -> None:
        now = datetime.now(timezone.utc)
        day_start = now - timedelta(days=1)
        month_start = now - timedelta(days=30)
        if self._spent_since(day_start) >= self.settings.openai_daily_limit:
            raise BudgetExceededError("Daily OpenAI budget limit reached")
        if self._spent_since(month_start) >= self.settings.openai_monthly_limit:
            raise BudgetExceededError("Monthly OpenAI budget limit reached")

    async def complete(self, messages: list[dict[str, str]]) -> LLMResponse:
        if not self.settings.openai_enabled:
            return LLMResponse(text="Estoy funcionando en modo local.", provider="local_disabled", model="none")
        if not self.client:
            return LLMResponse(text="OpenAI no está configurado. Sigo en modo local.", provider="local_missing_key", model="none")

        self._check_budget()
        try:
            result = await self.client.chat.completions.create(model=self.settings.openai_model, messages=messages, timeout=20)
        except (APITimeoutError, APIConnectionError, RateLimitError, AuthenticationError, APIError, httpx.HTTPError) as exc:
            raise LLMProviderError(exc.__class__.__name__) from exc
        text = result.choices[0].message.content or ""
        prompt_tokens = result.usage.prompt_tokens if result.usage else 0
        completion_tokens = result.usage.completion_tokens if result.usage else 0
        cost = self._estimate_cost(prompt_tokens, completion_tokens)
        self.db.add(
            OpenAIUsage(
                request_id=str(uuid.uuid4()),
                model=self.settings.openai_model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost=cost,
            )
        )
        self.db.commit()
        return LLMResponse(
            text=text,
            provider="openai",
            model=self.settings.openai_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost=cost,
            used_remote_model=True,
        )
