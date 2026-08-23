from sqlalchemy.orm import Session

from app.core.config import Settings
from app.llm.hetzner_provider import HetznerProvider
from app.llm.openai_provider import LLMProviderError, OpenAIProvider
from app.llm.provider import LLMProvider


def get_text_provider(settings: Settings, db: Session) -> LLMProvider:
    """Return the explicitly selected provider without silent paid fallback."""
    provider_name = settings.ali_text_provider.strip().lower()
    if provider_name == "hetzner":
        return HetznerProvider(settings, db)
    if provider_name == "openai":
        return OpenAIProvider(settings, db)
    raise LLMProviderError(f"unsupported_text_provider:{provider_name or 'empty'}")
