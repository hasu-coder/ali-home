import uuid
from datetime import datetime, timedelta, timezone
from math import ceil

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


class VoiceUnavailableError(RuntimeError):
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

    def _check_budget(self, reserve_cost: float = 0.0) -> None:
        now = datetime.now(timezone.utc)
        day_start = now - timedelta(days=1)
        month_start = now - timedelta(days=30)
        daily_spend = self._spent_since(day_start)
        monthly_spend = self._spent_since(month_start)
        if daily_spend >= self.settings.openai_daily_limit or daily_spend + reserve_cost >= self.settings.openai_daily_limit:
            raise BudgetExceededError("Daily OpenAI budget limit reached")
        if monthly_spend >= self.settings.openai_monthly_limit or monthly_spend + reserve_cost >= self.settings.openai_monthly_limit:
            raise BudgetExceededError("Monthly OpenAI budget limit reached")

    def _record_usage(self, *, model: str, prompt_tokens: int, completion_tokens: int, estimated_cost: float) -> None:
        self.db.add(
            OpenAIUsage(
                request_id=str(uuid.uuid4()),
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost=estimated_cost,
            )
        )
        self.db.commit()

    @property
    def transcription_available(self) -> bool:
        return bool(self.settings.openai_voice_enabled and self.client)

    @property
    def tts_available(self) -> bool:
        return bool(self.settings.openai_tts_enabled and self.client)

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
        self._record_usage(
            model=self.settings.openai_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost=cost,
        )
        return LLMResponse(
            text=text,
            provider="openai",
            model=self.settings.openai_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost=cost,
            used_remote_model=True,
        )

    async def transcribe_audio(self, *, filename: str, content_type: str, audio_bytes: bytes) -> tuple[str, float]:
        """Transcribe one short utterance without retaining the audio on disk."""
        if not self.transcription_available:
            raise VoiceUnavailableError("OpenAI voice transcription is not configured")

        reserved_cost = self.settings.ali_voice_max_seconds / 60 * self.settings.openai_transcription_cost_per_minute
        self._check_budget(reserve_cost=reserved_cost)
        try:
            result = await self.client.audio.transcriptions.create(
                model=self.settings.openai_transcription_model,
                file=(filename, audio_bytes, content_type),
                language=self.settings.ali_language,
                timeout=20,
            )
        except (APITimeoutError, APIConnectionError, RateLimitError, AuthenticationError, APIError, httpx.HTTPError) as exc:
            raise LLMProviderError(exc.__class__.__name__) from exc

        transcript = getattr(result, "text", "")
        if not isinstance(transcript, str) or not transcript.strip():
            raise LLMProviderError("empty_transcription")

        # We reserve the maximum request cost. It is deliberately conservative because
        # browser WebM duration cannot be safely trusted or decoded without extra codecs.
        self._record_usage(
            model=self.settings.openai_transcription_model,
            prompt_tokens=0,
            completion_tokens=0,
            estimated_cost=reserved_cost,
        )
        return transcript.strip(), reserved_cost

    async def synthesize_speech(self, text: str) -> tuple[bytes, float]:
        """Generate optional natural speech; browser speech remains the free default."""
        if not self.tts_available:
            raise VoiceUnavailableError("OpenAI text-to-speech is not configured")

        safe_text = text.strip()[: self.settings.ali_voice_max_reply_chars]
        if not safe_text:
            raise LLMProviderError("empty_speech_input")

        # ALI only speaks short answers. At roughly 150 words/minute this gives a
        # conservative estimate used solely for the local spending guardrail.
        estimated_seconds = max(1, ceil(len(safe_text.split()) / 2.5))
        reserved_cost = estimated_seconds / 60 * self.settings.openai_tts_estimated_cost_per_minute
        self._check_budget(reserve_cost=reserved_cost)
        try:
            response = await self.client.audio.speech.create(
                model=self.settings.openai_tts_model,
                voice=self.settings.openai_tts_voice,
                input=safe_text,
                instructions="Habla en español de forma cálida, clara y breve.",
                response_format="mp3",
                timeout=20,
            )
            audio = await response.aread()
        except (APITimeoutError, APIConnectionError, RateLimitError, AuthenticationError, APIError, httpx.HTTPError) as exc:
            raise LLMProviderError(exc.__class__.__name__) from exc

        if not audio:
            raise LLMProviderError("empty_speech_output")
        self._record_usage(
            model=self.settings.openai_tts_model,
            prompt_tokens=0,
            completion_tokens=0,
            estimated_cost=reserved_cost,
        )
        return audio, reserved_cost
