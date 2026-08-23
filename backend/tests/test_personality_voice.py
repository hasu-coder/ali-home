from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.llm.router import needs_remote_llm
from app.services.assistant import build_ali_instructions
from app.services.speech import home_context_line, speech_style_for_context


def test_quiet_hours_select_whisper():
    settings = Settings(ali_timezone="Europe/Madrid", ali_quiet_hours_start=23, ali_quiet_hours_end=7)
    at_three_am = datetime(2026, 8, 23, 3, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    assert speech_style_for_context(settings, room_key="dormitorio_matrimonio", now=at_three_am) == "whisper"


def test_daytime_uses_normal_voice():
    settings = Settings(ali_timezone="Europe/Madrid", ali_quiet_hours_start=23, ali_quiet_hours_end=7)
    afternoon = datetime(2026, 8, 23, 17, 30, tzinfo=ZoneInfo("Europe/Madrid"))
    assert speech_style_for_context(settings, room_key="cocina_salon", now=afternoon) == "normal"


def test_baby_room_is_soft_during_day():
    settings = Settings(ali_timezone="Europe/Madrid", ali_quiet_hours_start=23, ali_quiet_hours_end=7)
    afternoon = datetime(2026, 8, 23, 17, 30, tzinfo=ZoneInfo("Europe/Madrid"))
    assert speech_style_for_context(settings, room_key="habitacion_bebe", now=afternoon) == "soft"


def test_context_contains_local_time_room_and_style():
    settings = Settings(ali_timezone="Europe/Madrid", ali_quiet_hours_start=23, ali_quiet_hours_end=7)
    at_three_am = datetime(2026, 8, 23, 3, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    context = home_context_line(settings, room_key="dormitorio_matrimonio", now=at_three_am)
    assert "03:00" in context
    assert "dormitorio_matrimonio" in context
    assert "whisper" in context


def test_personality_prompt_has_requested_modes():
    prompt = build_ali_instructions(None, context_line="Contexto actual: hora local 18:00, estancia cocina_salon.")
    assert "irónica" in prompt
    assert "sarcástica" in prompt
    assert "ansiedad" in prompt
    assert "chef" in prompt
    assert "No diagnostiques" in prompt
    assert "no sustituyas ayuda profesional" in prompt


def test_conversation_examples_route_to_llm_not_home_automation():
    examples = [
        "ALI, te voy a apagar",
        "ALI, me siento con ansiedad",
        "ALI, ¿cómo hago un tajín de verduras?",
        "ALI, estoy agobiada y no sé por dónde empezar",
    ]
    assert all(needs_remote_llm(text) for text in examples)
