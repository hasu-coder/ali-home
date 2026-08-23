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

    ali_wake_word: str = "ALI"
    ali_language: str = "es"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.ali_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
