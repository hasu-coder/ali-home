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
            result = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=messages,
                max_tokens=self.settings.openai_max_output_tokens,
                timeout=20,
            )
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

    async def complete_with_web(self, messages: list[dict[str, str]]) -> LLMResponse:
        """Use current public information only when ALI detects that freshness matters.

        This uses the Responses API directly so the project is not coupled to a
        particular Python SDK representation of the web-search tool.
        """
        if not self.settings.openai_enabled:
            raise LLMProviderError("live_context_requires_openai")
        if not self.settings.openai_live_context_enabled:
            raise LLMProviderError("live_context_disabled")
        if not self.settings.openai_api_key:
            raise LLMProviderError("missing_openai_key")

        reserve = self.settings.openai_web_search_cost_per_call
        self._check_budget(reserve_cost=reserve)
        payload = {
            "model": self.settings.openai_live_model,
            "input": messages,
            "tools": [{"type": "web_search"}],
            "max_output_tokens": self.settings.openai_max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMProviderError("web_search_failed") from exc

        text_parts: list[str] = []
        for item in data.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    text_parts.append(str(content["text"]))
        text = "\n".join(text_parts).strip()
        if not text:
            raise LLMProviderError("empty_live_response")

        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("input_tokens") or 0)
        completion_tokens = int(usage.get("output_tokens") or 0)
        cost = self._estimate_cost(prompt_tokens, completion_tokens) + self.settings.openai_web_search_cost_per_call
        self._record_usage(
            model=f"{self.settings.openai_live_model}+web",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost=cost,
        )
        return LLMResponse(
            text=text,
            provider="openai_web",
            model=self.settings.openai_live_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost=cost,
            used_remote_model=True,
        )

    def transcription_cost_for_seconds(self, duration_seconds: float | None) -> float:
        """Estimate a clip by its measured client duration, never a fixed block."""
        seconds = duration_seconds if duration_seconds is not None else self.settings.ali_voice_max_seconds
        seconds = min(float(self.settings.ali_voice_max_seconds), max(0.25, float(seconds)))
        return seconds / 60 * self.settings.openai_transcription_cost_per_minute

    async def transcribe_audio(
        self,
        *,
        filename: str,
        content_type: str,
        audio_bytes: bytes,
        duration_seconds: float | None = None,
    ) -> tuple[str, float]:
        """Paid cloud fallback. Normal ALI operation should use faster-whisper locally."""
        if not self.transcription_available:
            raise VoiceUnavailableError("OpenAI voice transcription is not configured")

        maximum_cost = self.transcription_cost_for_seconds(self.settings.ali_voice_max_seconds)
        self._check_budget(reserve_cost=maximum_cost)
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

        self._record_usage(
            model=self.settings.openai_transcription_model,
            prompt_tokens=0,
            completion_tokens=0,
            estimated_cost=self.transcription_cost_for_seconds(duration_seconds),
        )
        return transcript.strip(), self.transcription_cost_for_seconds(duration_seconds)

    async def synthesize_speech(self, text: str, style: str = "normal") -> tuple[bytes, float]:
        """Generate optional natural speech; local/browser speech remains the free default."""
        if not self.tts_available:
            raise VoiceUnavailableError("OpenAI text-to-speech is not configured")

        safe_text = text.strip()[: self.settings.ali_voice_max_reply_chars]
        if not safe_text:
            raise LLMProviderError("empty_speech_input")

        style = style if style in {"normal", "soft", "whisper"} else "normal"
        style_instruction = {
            "normal": "Habla con un volumen normal y una energía cercana.",
            "soft": "Habla suave, cálida y discretamente, como si hubiera alguien descansando cerca.",
            "whisper": "Habla en un susurro claro y natural, muy bajo y calmado, sin dramatizar.",
        }[style]

        estimated_seconds = max(1, ceil(len(safe_text.split()) / 3))
        reserved_cost = estimated_seconds / 60 * self.settings.openai_tts_estimated_cost_per_minute
        self._check_budget(reserve_cost=reserved_cost)
        try:
            response = await self.client.audio.speech.create(
                model=self.settings.openai_tts_model,
                voice=self.settings.openai_tts_voice,
                input=safe_text,
                instructions=(
                    "Eres la voz fija de ALI, la compañera digital de hogar de Ismael y Laura. Habla en español "
                    "de España con una voz femenina, cálida, inteligente y natural. Mantén un ritmo ágil y cercano, "
                    "con pausas breves y frases vivas. Nada de tono robótico, dramático ni de locutora. "
                    f"{style_instruction}"
                ),
                response_format="mp3",
                speed=self.settings.openai_tts_speed,
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
