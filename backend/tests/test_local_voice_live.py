from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.llm.provider import LLMResponse
from app.main import app
from app.services.live_context import needs_live_context
from app.services.local_voice import SpeakerMatch, cosine_similarity, normalize_embedding


client = TestClient(app)


def test_live_context_detects_conversational_barca_example():
    assert needs_live_context("ALI, estoy viendo el Barça") is True
    assert needs_live_context("¿Cómo van en el partido del Barcelona?") is True
    assert needs_live_context("Cuéntame la historia del FC Barcelona") is False


def test_live_context_detects_current_news_weather_traffic_and_prices():
    assert needs_live_context("¿Qué tiempo hace hoy?") is True
    assert needs_live_context("¿Qué ha pasado hoy en las noticias?") is True
    assert needs_live_context("¿Hay atasco ahora?") is True
    assert needs_live_context("¿A cuánto está el euribor?") is True


def test_cosine_similarity_is_suitable_for_local_voiceprints():
    left = normalize_embedding([1.0, 1.0, 0.0])
    same = normalize_embedding([2.0, 2.0, 0.0])
    different = normalize_embedding([-1.0, -1.0, 0.0])
    assert cosine_similarity(left, same) > 0.99
    assert cosine_similarity(left, different) < 0.0


def test_live_context_turn_uses_web_capable_provider(monkeypatch):
    captured = {"web": 0, "normal": 0}

    class FakeLiveProvider:
        def __init__(self, settings, db):
            pass

        async def complete(self, messages):
            captured["normal"] += 1
            return LLMResponse(text="normal", provider="test", model="test", used_remote_model=True)

        async def complete_with_web(self, messages):
            captured["web"] += 1
            return LLMResponse(
                text="He comprobado el partido antes de responder.",
                provider="test-web",
                model="test-web",
                used_remote_model=True,
            )

    settings = get_settings()
    previous = settings.openai_enabled
    settings.openai_enabled = True
    monkeypatch.setattr("app.api.routes.OpenAIProvider", FakeLiveProvider)
    try:
        response = client.post(
            "/api/ask",
            json={"text": "ALI, estoy viendo el Barça", "probable_user": "ismael"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["live_context_used"] is True
        assert captured["web"] == 1
        assert captured["normal"] == 0
    finally:
        settings.openai_enabled = previous


def test_voice_turn_prefers_detected_speaker_over_manual_fallback(monkeypatch):
    class FakeLocalVoiceEngine:
        def __init__(self, settings):
            pass

        async def transcribe_async(self, audio):
            return "ALI, recuerda que mi color de prueba es verde"

        async def identify_async(self, db, audio):
            return SpeakerMatch(username="laura", similarity=0.91, accepted=True)

    monkeypatch.setattr("app.api.routes.LocalVoiceEngine", FakeLocalVoiceEngine)
    response = client.post(
        "/api/voice/turn",
        data={"probable_user": "ismael", "room_key": "cocina_salon", "duration_seconds": "2.0"},
        files={"file": ("sample.wav", b"not-real-audio", "audio/wav")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["speaker"] == "laura"
    assert body["speaker_identified"] is True
    assert body["probable_user"] == "laura"
    assert body["transcription_source"] == "local"
    assert body["transcription_estimated_cost"] == 0.0
