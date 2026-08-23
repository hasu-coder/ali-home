from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ali_env: str = "development"
    ali_log_level: str = "INFO"
    ali_database_url: str = "sqlite:///./data/ali.db"
    ali_cors_origins: str = "http://localhost:5173,http://localhost:3000"
    ali_timezone: str = "Europe/Madrid"
    ali_quiet_hours_start: int = Field(default=23, ge=0, le=23)
    ali_quiet_hours_end: int = Field(default=7, ge=0, le=23)

    home_assistant_url: str = "http://homeassistant.local:8123"
    home_assistant_token: str = ""
    home_assistant_enabled: bool = False
    # Leave these empty until the real entity IDs are known. This prevents ALI
    # from guessing an entity and claiming that a physical action was carried out.
    home_assistant_cover_entity_id: str = ""
    home_assistant_climate_entity_id: str = ""

    openai_api_key: str = ""
    # Text reasoning is the only normal paid path. House control, STT and speaker
    # recognition are designed to stay local.
    openai_model: str = "gpt-4o-mini"
    openai_enabled: bool = False
    openai_monthly_limit: float = 5.0
    openai_daily_limit: float = 1.0
    openai_soft_monthly_warning: float = 2.0
    openai_input_cost_per_1m: float = Field(default=0.15, ge=0)
    openai_output_cost_per_1m: float = Field(default=0.60, ge=0)
    openai_max_output_tokens: int = Field(default=120, ge=16, le=1024)

    # Normal conversation can use Hetzner's OpenAI-compatible Qwen endpoint
    # without sending the key to the browser or applying OpenAI spend limits.
    ali_text_provider: str = "hetzner"
    hetzner_inference_api_key: str = ""
    hetzner_inference_base_url: str = "https://inference.hetzner.com/api/v1"
    hetzner_inference_model: str = "Qwen/Qwen3.6-35B-A3B-FP8"

    # Current information is opt-in and only invoked when the utterance implies
    # fresh data (live sport, weather, news, traffic, prices, etc.).
    openai_live_context_enabled: bool = True
    openai_live_model: str = "gpt-4o-mini"
    openai_web_search_cost_per_call: float = Field(default=0.01, ge=0)

    # Paid cloud voice remains an optional fallback. It is NOT the default path.
    openai_voice_enabled: bool = False
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    openai_transcription_cost_per_minute: float = Field(default=0.003, ge=0)
    openai_tts_enabled: bool = False
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "coral"
    openai_tts_speed: float = Field(default=1.2, ge=0.25, le=4.0)
    openai_tts_estimated_cost_per_minute: float = Field(default=0.015, ge=0)

    # Local voice: faster-whisper transcribes for €0/API call and SpeechBrain
    # identifies enrolled residents locally. Models are cached in ali_data.
    ali_local_stt_enabled: bool = True
    ali_local_stt_model: str = "small"
    ali_local_stt_device: str = "cpu"
    ali_local_stt_compute_type: str = "int8"
    ali_speaker_id_enabled: bool = True
    ali_speaker_model: str = "speechbrain/spkrec-ecapa-voxceleb"
    ali_speaker_threshold: float = Field(default=0.62, ge=-1.0, le=1.0)
    ali_voice_model_cache: str = "/app/data/models"
    ali_voice_max_bytes: int = Field(default=4_000_000, ge=100_000, le=25_000_000)
    ali_voice_max_seconds: int = Field(default=8, ge=1, le=120)
    ali_voice_max_reply_chars: int = Field(default=180, ge=50, le=4096)

    ali_wake_word: str = "ALI"
    ali_language: str = "es"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.ali_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
