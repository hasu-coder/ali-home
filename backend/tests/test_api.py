from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.llm.provider import LLMResponse
from app.llm.openai_provider import BudgetExceededError, OpenAIProvider
from app.llm.router import needs_remote_llm
from app.main import app
from app.services.assistant import remove_automatic_follow_up
from app.models.entities import ActivityLog, MemoryItem, OpenAIUsage


client = TestClient(app)


class FakeHAResult:
    def __init__(self, success=True, verified=True, state="on", error=None, status_code=200):
        self.success = success
        self.verified = verified
        self.state = state
        self.error = error
        self.status_code = status_code


class FakeHomeAssistantClient:
    calls = []
    result = FakeHAResult()
    health_result = {"enabled": True, "reachable": True}

    def __init__(self, settings):
        self.settings = settings

    async def health(self):
        return self.health_result

    async def execute_intent(self, intent):
        self.__class__.calls.append(intent)
        return self.result


def test_health_returns_ali_core_status():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["service"] == "ali-core"


def test_status_reports_database_and_optional_integrations():
    response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["database"]["status"] == "ok"
    assert body["openai"]["enabled"] in {True, False}
    assert body["home_assistant"]["enabled"] in {True, False}


def test_home_assistant_offline_does_not_break_status(monkeypatch):
    class OfflineHAClient:
        def __init__(self, settings):
            pass

        async def health(self):
            raise TimeoutError("offline")

    monkeypatch.setattr("app.api.routes.HomeAssistantClient", OfflineHAClient)
    response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["home_assistant"]["reachable"] is False


def test_bootstrap_users_rooms_and_cat():
    assert {user["username"] for user in client.get("/api/users").json()} >= {"laura", "ismael"}
    assert any(room["key"] == "dormitorio_matrimonio" for room in client.get("/api/rooms").json())
    assert client.get("/api/pets").json()[0]["species"] == "cat"


def test_local_ask_does_not_use_remote_llm_for_known_light_intent(monkeypatch):
    FakeHomeAssistantClient.calls = []
    FakeHomeAssistantClient.result = FakeHAResult(success=True, verified=True, state="on")
    monkeypatch.setattr("app.api.routes.HomeAssistantClient", FakeHomeAssistantClient)
    response = client.post("/api/ask", json={"text": "ALI, enciende la cocina", "probable_user": "ismael"})
    assert response.status_code == 200
    body = response.json()
    assert body["used_remote_llm"] is False
    assert body["response"] == "Vale, enciendo la cocina."
    assert body["intent"]["intent"] == "set_room_lighting"
    assert body["execution"]["success"] is True
    assert FakeHomeAssistantClient.calls[0]["entity_id"] == "light.cocina_salon"


def test_local_router_keeps_known_home_commands_off_openai():
    known_local = [
        "enciende la cocina",
        "apaga el salón",
        "modo noche",
        "nos vamos",
        "qué temperatura hace",
        "baja las persianas",
        "enciende el aire acondicionado",
        "pon el aire a 22 grados",
    ]
    assert all(needs_remote_llm(text) is False for text in known_local)


def test_short_natural_language_requests_can_use_ali():
    assert needs_remote_llm("¿Qué puedes hacer?") is True
    assert needs_remote_llm("hola") is True
    assert needs_remote_llm("¿Qué puedo cocinar esta noche?") is True


def test_unconfigured_blinds_stay_local_and_do_not_claim_success():
    response = client.post("/api/ask", json={"text": "ALI, baja las persianas", "probable_user": "ismael"})
    assert response.status_code == 200
    body = response.json()
    assert body["used_remote_llm"] is False
    assert body["execution"] is None
    assert body["response"] == "Aún no tengo las persianas enlazadas a Home Assistant."


def test_configured_air_uses_local_home_assistant_intent(monkeypatch):
    settings = get_settings()
    original_entity_id = settings.home_assistant_climate_entity_id
    FakeHomeAssistantClient.calls = []
    FakeHomeAssistantClient.result = FakeHAResult(success=True, verified=False, state=None)
    settings.home_assistant_climate_entity_id = "climate.salon"
    monkeypatch.setattr("app.api.routes.HomeAssistantClient", FakeHomeAssistantClient)
    try:
        response = client.post("/api/ask", json={"text": "ALI, pon el aire a 22 grados", "probable_user": "ismael"})
        assert response.status_code == 200
        body = response.json()
        assert body["used_remote_llm"] is False
        assert body["response"] == "Vale, dejo el aire a 22 grados."
        assert FakeHomeAssistantClient.calls[0]["entity_id"] == "climate.salon"
        assert FakeHomeAssistantClient.calls[0]["service_data"] == {"temperature": 22}
    finally:
        settings.home_assistant_climate_entity_id = original_entity_id


def test_ali_removes_canned_closing_questions():
    assert remove_automatic_follow_up("Eres Ismael. ¿Quieres que te ayude con algo más?") == "Eres Ismael."
    assert remove_automatic_follow_up("Ey, Ismael. ¿Qué necesitas?") == "Ey, Ismael."
    assert remove_automatic_follow_up("Necesito saber la habitación. ¿En cuál estás?") == "Necesito saber la habitación. ¿En cuál estás?"


def test_transcription_estimate_uses_measured_duration_not_the_maximum():
    settings = get_settings()
    provider = OpenAIProvider(settings, SessionLocal())
    try:
        short_clip = provider.transcription_cost_for_seconds(1.0)
        maximum_clip = provider.transcription_cost_for_seconds(settings.ali_voice_max_seconds)
        assert short_clip < maximum_clip
        assert short_clip == settings.openai_transcription_cost_per_minute / 60
    finally:
        provider.db.close()


def test_conversation_session_is_created_and_reused(monkeypatch):
    FakeHomeAssistantClient.calls = []
    FakeHomeAssistantClient.result = FakeHAResult(success=True, verified=True, state="on")
    monkeypatch.setattr("app.api.routes.HomeAssistantClient", FakeHomeAssistantClient)
    first = client.post("/api/ask", json={"text": "ALI, enciende la cocina", "probable_user": "ismael"})
    assert first.status_code == 200
    conversation_id = first.json()["conversation_id"]
    second = client.post(
        "/api/ask",
        json={"text": "apaga el salón", "conversation_id": conversation_id, "probable_user": "ismael"},
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id


def test_home_assistant_command_failure_does_not_claim_success(monkeypatch):
    FakeHomeAssistantClient.calls = []
    FakeHomeAssistantClient.result = FakeHAResult(success=False, verified=True, state="off", error="expected_on_got_off")
    monkeypatch.setattr("app.api.routes.HomeAssistantClient", FakeHomeAssistantClient)

    response = client.post("/api/ask", json={"text": "ALI, enciende la cocina", "probable_user": "ismael"})
    assert response.status_code == 200
    body = response.json()
    assert body["used_remote_llm"] is False
    assert body["response"] == "No he podido encender la cocina."
    assert body["execution"]["success"] is False


def test_home_assistant_disabled_command_returns_disconnected(monkeypatch):
    FakeHomeAssistantClient.calls = []
    FakeHomeAssistantClient.result = FakeHAResult(success=False, verified=False, state=None, error="home_assistant_disabled")
    monkeypatch.setattr("app.api.routes.HomeAssistantClient", FakeHomeAssistantClient)

    response = client.post("/api/ask", json={"text": "ALI, enciende la cocina", "probable_user": "ismael"})
    assert response.status_code == 200
    assert response.json()["response"] == "Ahora mismo no puedo comunicarme con la casa."


def test_memory_remember_search_list_and_forget():
    created = client.post(
        "/api/memory",
        json={
            "scope": "ismael",
            "kind": "PERSONAL_MEMORY",
            "owner": "ismael",
            "title": "Temperatura para dormir",
            "content": "A Ismael le gusta dormir a 21 grados.",
            "tags": ["clima", "dormitorio"],
        },
    )
    assert created.status_code == 200
    memory_id = created.json()["id"]
    assert any(item["id"] == memory_id for item in client.get("/api/memory?q=dormir").json())
    assert any(item["id"] == memory_id for item in client.get("/api/memory/search?q=21").json())
    deleted = client.delete(f"/api/memory/{memory_id}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"


def test_ali_saves_only_explicitly_requested_memories():
    response = client.post(
        "/api/ask",
        json={"text": "ALI, recuerda que prefiero el salón a 21 grados", "probable_user": "ismael"},
    )
    assert response.status_code == 200
    assert response.json()["response"] == "Vale, lo tendré presente."
    assert response.json()["intent"]["intent"] == "remember"
    memories = client.get("/api/memory?q=salón").json()
    assert any(item["owner"] == "ismael" and "21 grados" in item["content"] for item in memories)


def test_activity_log_has_required_shape():
    response = client.get("/api/activity")
    assert response.status_code == 200
    item = response.json()[0]
    for field in ["created_at", "actor", "source", "action", "result", "details"]:
        assert field in item
    assert "llm_used" in item
    assert "estimated_cost" in item


def test_openai_disabled_does_not_block_complex_question():
    settings = get_settings()
    original = settings.openai_enabled
    settings.openai_enabled = False
    try:
        response = client.post(
            "/api/ask",
            json={"text": "ALI, explícame con detalle cómo organizar una cena tranquila", "probable_user": "laura"},
        )
        assert response.status_code == 200
        assert response.json()["used_remote_llm"] is False
    finally:
        settings.openai_enabled = original


def test_openai_enabled_default_is_false():
    assert get_settings().openai_enabled is False


def test_openai_provider_error_falls_back_to_local(monkeypatch):
    class FailingProvider:
        def __init__(self, settings, db):
            pass

        async def complete(self, messages):
            from app.llm.openai_provider import LLMProviderError

            raise LLMProviderError("offline")

    settings = get_settings()
    original_enabled = settings.openai_enabled
    settings.openai_enabled = True
    monkeypatch.setattr("app.api.routes.OpenAIProvider", FailingProvider)
    try:
        response = client.post(
            "/api/ask",
            json={"text": "ALI, explícame con detalle cómo organizar una cena tranquila", "probable_user": "laura"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["used_remote_llm"] is False
        assert body["response"] == "Ahora mismo estoy funcionando en modo local."
    finally:
        settings.openai_enabled = original_enabled


def test_openai_budget_limit_keeps_local_home_control_working(monkeypatch):
    class BudgetProvider:
        def __init__(self, settings, db):
            pass

        async def complete(self, messages):
            raise BudgetExceededError("Monthly OpenAI budget limit reached")

    FakeHomeAssistantClient.calls = []
    FakeHomeAssistantClient.result = FakeHAResult(success=True, verified=True, state="on")
    settings = get_settings()
    original_enabled = settings.openai_enabled
    settings.openai_enabled = True
    monkeypatch.setattr("app.api.routes.OpenAIProvider", BudgetProvider)
    monkeypatch.setattr("app.api.routes.HomeAssistantClient", FakeHomeAssistantClient)
    try:
        remote = client.post(
            "/api/ask",
            json={"text": "ALI, explícame con detalle cómo organizar una cena tranquila", "probable_user": "laura"},
        )
        local = client.post("/api/ask", json={"text": "ALI, enciende la cocina", "probable_user": "ismael"})
        assert remote.status_code == 200
        assert "modo local" in remote.json()["response"]
        assert local.status_code == 200
        assert local.json()["response"] == "Vale, enciendo la cocina."
        assert local.json()["used_remote_llm"] is False
    finally:
        settings.openai_enabled = original_enabled


def test_conversation_session_sends_recent_history_to_llm(monkeypatch):
    captured = {}

    class CapturingProvider:
        def __init__(self, settings, db):
            pass

        async def complete(self, messages):
            captured["messages"] = messages
            return LLMResponse(
                text="Por la tarde hará más fresco.",
                provider="test",
                model="test-model",
                used_remote_model=True,
            )

    settings = get_settings()
    original_enabled = settings.openai_enabled
    settings.openai_enabled = True
    monkeypatch.setattr("app.api.routes.OpenAIProvider", CapturingProvider)
    try:
        first = client.post(
            "/api/ask",
            json={"text": "ALI, ¿qué tiempo hará mañana por la mañana en Madrid?", "probable_user": "ismael"},
        )
        conversation_id = first.json()["conversation_id"]
        second = client.post(
            "/api/ask",
            json={
                "text": "¿Y por la tarde exactamente qué debería esperar?",
                "conversation_id": conversation_id,
                "probable_user": "ismael",
            },
        )
        assert second.status_code == 200
        contents = [message["content"] for message in captured["messages"]]
        assert any("La persona que habla es Ismael" in content for content in contents)
        assert any("No cierres las respuestas con una pregunta" in content for content in contents)
        assert any("mañana por la mañana" in content for content in contents)
        assert any("por la tarde exactamente" in content for content in contents)
        assert len(captured["messages"]) <= 10
    finally:
        settings.openai_enabled = original_enabled


def test_openai_budget_hard_limit_blocks_remote_provider_only():
    settings = get_settings()
    original_daily = settings.openai_daily_limit
    original_monthly = settings.openai_monthly_limit
    settings.openai_daily_limit = 0.0
    settings.openai_monthly_limit = 0.0
    db = SessionLocal()
    try:
        provider = OpenAIProvider(settings, db)
        try:
            provider._check_budget()
        except BudgetExceededError:
            pass
        else:
            raise AssertionError("OpenAI budget should be exceeded")
    finally:
        db.close()
        settings.openai_daily_limit = original_daily
        settings.openai_monthly_limit = original_monthly


def test_openai_usage_schema_tracks_tokens_and_cost():
    db = SessionLocal()
    try:
        existing = db.query(OpenAIUsage).filter_by(request_id="test-openai-usage-schema").first()
        if existing:
            db.delete(existing)
            db.commit()
        row = OpenAIUsage(
            request_id="test-openai-usage-schema",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=5,
            estimated_cost=0.001,
        )
        db.add(row)
        db.commit()
        saved = db.query(OpenAIUsage).filter_by(request_id="test-openai-usage-schema").first()
        assert saved is not None
        assert saved.prompt_tokens == 10
        assert saved.completion_tokens == 5
        assert saved.estimated_cost == 0.001
        db.delete(saved)
        db.commit()
    finally:
        db.close()


def test_home_assistant_disabled_reports_disconnected():
    settings = get_settings()
    original = settings.home_assistant_enabled
    settings.home_assistant_enabled = False
    try:
        response = client.get("/api/integrations/homeassistant/health")
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        assert body["reachable"] is False
    finally:
        settings.home_assistant_enabled = original


def test_configuration_errors_do_not_expose_secrets_publicly():
    public = client.get("/api/config/public").json()
    assert "openai_api_key" not in public
    assert "home_assistant_token" not in public


def test_persistence_logic_uses_database_rows_not_in_memory_state():
    db = SessionLocal()
    try:
        memory_count = db.query(MemoryItem).count()
        activity_count = db.query(ActivityLog).count()
        assert isinstance(memory_count, int)
        assert activity_count >= 1
    finally:
        db.close()


def test_voice_status_is_public_but_never_contains_the_api_key():
    settings = get_settings()
    original_key = settings.openai_api_key
    original_enabled = settings.openai_voice_enabled
    settings.openai_api_key = "test-secret-must-not-leak"
    settings.openai_voice_enabled = True
    try:
        body = client.get("/api/status").json()
        assert body["voice"]["transcription_available"] is True
        assert "test-secret-must-not-leak" not in str(body)
    finally:
        settings.openai_api_key = original_key
        settings.openai_voice_enabled = original_enabled


def test_voice_turn_is_unavailable_until_explicitly_enabled():
    settings = get_settings()
    original = settings.openai_voice_enabled
    settings.openai_voice_enabled = False
    try:
        response = client.post(
            "/api/voice/turn",
            files={"file": ("voice.webm", b"short-audio", "audio/webm")},
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "voice_transcription_unavailable"
    finally:
        settings.openai_voice_enabled = original


def test_voice_turn_rejects_unexpected_file_types():
    response = client.post(
        "/api/voice/turn",
        files={"file": ("voice.txt", b"not-audio", "text/plain")},
    )
    assert response.status_code == 415
    assert response.json()["detail"] == "unsupported_voice_format"


def test_voice_turn_uses_the_same_local_command_path_and_withholds_transcript(monkeypatch):
    class FakeVoiceProvider:
        def __init__(self, settings, db):
            pass

        async def transcribe_audio(self, *, filename, content_type, audio_bytes, duration_seconds=None):
            assert filename == "voice.webm"
            assert content_type == "audio/webm"
            assert audio_bytes == b"short-audio"
            return "ALI, enciende la cocina", 0.001

    settings = get_settings()
    original = settings.openai_voice_enabled
    settings.openai_voice_enabled = True
    FakeHomeAssistantClient.calls = []
    FakeHomeAssistantClient.result = FakeHAResult(success=True, verified=True, state="on")
    monkeypatch.setattr("app.api.routes.OpenAIProvider", FakeVoiceProvider)
    monkeypatch.setattr("app.api.routes.HomeAssistantClient", FakeHomeAssistantClient)
    try:
        response = client.post(
            "/api/voice/turn",
            files={"file": ("voice.webm", b"short-audio", "audio/webm")},
            data={"probable_user": "ismael", "room_key": "cocina_salon"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["transcript"] == "ALI, enciende la cocina"
        assert body["response"] == "Vale, enciendo la cocina."
        assert body["used_remote_llm"] is False
        assert body["transcription_estimated_cost"] == 0.001
        assert FakeHomeAssistantClient.calls[0]["entity_id"] == "light.cocina_salon"
        db = SessionLocal()
        try:
            voice_log = db.query(ActivityLog).filter_by(event_type="voice.transcribed").order_by(ActivityLog.id.desc()).first()
            assert voice_log is not None
            assert "enciende la cocina" not in voice_log.details
        finally:
            db.close()
    finally:
        settings.openai_voice_enabled = original


def test_openai_tts_stays_opt_in():
    settings = get_settings()
    original = settings.openai_tts_enabled
    settings.openai_tts_enabled = False
    try:
        response = client.post("/api/voice/speech", json={"text": "Hola"})
        assert response.status_code == 503
        assert response.json()["detail"] == "voice_synthesis_unavailable"
    finally:
        settings.openai_tts_enabled = original
