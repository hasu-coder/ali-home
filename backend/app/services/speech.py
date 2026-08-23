from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import Settings


VALID_SPEECH_STYLES = {"normal", "soft", "whisper"}


def local_now(settings: Settings) -> datetime:
    try:
        timezone = ZoneInfo(settings.ali_timezone)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return datetime.now(timezone)


def is_quiet_hour(settings: Settings, now: datetime | None = None) -> bool:
    current = now or local_now(settings)
    start = settings.ali_quiet_hours_start
    end = settings.ali_quiet_hours_end
    hour = current.hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def speech_style_for_context(
    settings: Settings,
    *,
    room_key: str | None = None,
    now: datetime | None = None,
) -> str:
    current = now or local_now(settings)
    if is_quiet_hour(settings, current):
        return "whisper"
    if room_key == "habitacion_bebe":
        return "soft"
    return "normal"


def home_context_line(settings: Settings, *, room_key: str | None = None, now: datetime | None = None) -> str:
    current = now or local_now(settings)
    room = room_key or "desconocida"
    style = speech_style_for_context(settings, room_key=room_key, now=current)
    return (
        f"Contexto actual: hora local {current.strftime('%H:%M')}, estancia {room}, "
        f"estilo de voz recomendado {style}."
    )
