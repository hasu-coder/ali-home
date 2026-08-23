from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ali_env: str = "development"
    ali_log_level: str = "INFO"
    ali_database_url: str = "sqlite:///./data/ali.db"
    ali_cors_origins: str = "http://localhost:5173,http://localhost:3000"

    home_assistant_url: str = "http://homeassistant.local:8123"
    home_assistant_token: str = ""
    home_assistant_enabled: bool = False

    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    openai_enabled: bool = False
    openai_monthly_limit: float = 5.0
    openai_daily_limit: float = 1.0
    openai_soft_monthly_warning: float = 2.0
    openai_input_cost_per_1m: float = Field(default=0.40, ge=0)
    openai_output_cost_per_1m: float = Field(default=1.60, ge=0)

    # Voice is intentionally opt-in. The browser never receives the API key.
    openai_voice_enabled: bool = False
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    openai_transcription_cost_per_minute: float = Field(default=0.003, ge=0)
    openai_tts_enabled: bool = False
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "coral"
    openai_tts_estimated_cost_per_minute: float = Field(default=0.015, ge=0)
    ali_voice_max_bytes: int = Field(default=4_000_000, ge=100_000, le=25_000_000)
    ali_voice_max_seconds: int = Field(default=20, ge=1, le=120)
    ali_voice_max_reply_chars: int = Field(default=480, ge=50, le=4096)

    ali_wake_word: str = "ALI"
    ali_language: str = "es"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.ali_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
