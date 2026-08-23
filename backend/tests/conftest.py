import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def deterministic_test_settings(request):
    """Keep tests independent from the developer's runtime .env.

    The real Codespace may deliberately have OPENAI_ENABLED=true while testing
    conversation features. Unit tests must still verify the product defaults,
    which are OpenAI off unless a test explicitly enables it.

    Two Phase-1 voice tests predate local faster-whisper and intentionally test
    the old paid-STT fallback contract. Disable local STT only for those tests;
    the v0.4 local-voice tests exercise the new default path separately.
    """
    settings = get_settings()
    original_openai_enabled = settings.openai_enabled
    original_local_stt_enabled = settings.ali_local_stt_enabled

    settings.openai_enabled = False
    if request.node.name in {
        "test_voice_turn_is_unavailable_until_explicitly_enabled",
        "test_voice_turn_uses_the_same_local_command_path_and_withholds_transcript",
    }:
        settings.ali_local_stt_enabled = False

    try:
        yield
    finally:
        settings.openai_enabled = original_openai_enabled
        settings.ali_local_stt_enabled = original_local_stt_enabled
