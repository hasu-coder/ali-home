import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.integrations.homeassistant.client import HomeAssistantClient
from app.llm.openai_provider import BudgetExceededError, LLMProviderError, OpenAIProvider, VoiceUnavailableError
from app.models.entities import ActivityLog, ConversationSession, MemoryItem, OpenAIUsage, Pet, Room, UserProfile
from app.services.activity import log_activity
from app.services.assistant import run_assistant_turn
from app.services.conversation import create_conversation
from app.services.memory import memory_to_dict, search_memory

router = APIRouter()


class MemoryCreate(BaseModel):
    scope: str
    kind: str
    title: str
    content: str
    owner: str | None = None
    tags: list[str] = Field(default_factory=list)
    source: str = "manual"


class ConversationCreate(BaseModel):
    probable_user: str | None = None
    room_key: str | None = None
    voice_point: str | None = None
    confidence: float = 0.0


class AskRequest(BaseModel):
    text: str
    conversation_id: str | None = None
    probable_user: str | None = None
    room_key: str | None = None


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=480)


SUPPORTED_VOICE_CONTENT_TYPES = {
    "audio/aac",
    "audio/flac",
    "audio/m4a",
    "audio/mp3",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "audio/x-wav",
}


def row_to_dict(row: Any) -> dict:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "status": "ok",
        "service": "ali-core",
        "environment": settings.ali_env,
    }


@router.get("/status")
async def status(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    try:
        home_assistant = await HomeAssistantClient(settings).health()
    except Exception as exc:
        home_assistant = {"enabled": settings.home_assistant_enabled, "reachable": False, "error": exc.__class__.__name__}
    return {
        "status": "ok",
        "service": "ali-core",
        "database": {
            "status": "ok",
            "users": db.query(UserProfile).count(),
            "rooms": db.query(Room).count(),
            "pets": db.query(Pet).count(),
            "memories": db.query(MemoryItem).count(),
            "activity": db.query(ActivityLog).count(),
            "conversations": db.query(ConversationSession).count(),
        },
        "openai": {
            "enabled": settings.openai_enabled,
            "configured": bool(settings.openai_api_key),
        },
        "voice": {
            "transcription_available": bool(settings.openai_voice_enabled and settings.openai_api_key),
            "tts_available": bool(settings.openai_tts_enabled and settings.openai_api_key),
            "max_seconds": settings.ali_voice_max_seconds,
            "transcription_model": settings.openai_transcription_model,
        },
        "home_assistant": home_assistant,
    }


@router.get("/config/public")
def public_config(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "wake_word": settings.ali_wake_word,
        "language": settings.ali_language,
        "openai_enabled": settings.openai_enabled,
        "openai_monthly_limit": settings.openai_monthly_limit,
        "openai_soft_monthly_warning": settings.openai_soft_monthly_warning,
        "voice_transcription_available": bool(settings.openai_voice_enabled and settings.openai_api_key),
        "voice_tts_available": bool(settings.openai_tts_enabled and settings.openai_api_key),
        "voice_max_seconds": settings.ali_voice_max_seconds,
        "home_assistant_enabled": settings.home_assistant_enabled,
    }


@router.get("/users")
def users(db: Session = Depends(get_db)) -> list[dict]:
    return [row_to_dict(user) for user in db.query(UserProfile).order_by(UserProfile.display_name).all()]


@router.get("/rooms")
def rooms(db: Session = Depends(get_db)) -> list[dict]:
    result = []
    for room in db.query(Room).order_by(Room.floor, Room.name).all():
        data = row_to_dict(room)
        data["aliases"] = json.loads(room.aliases or "[]")
        result.append(data)
    return result


@router.get("/pets")
def pets(db: Session = Depends(get_db)) -> list[dict]:
    return [row_to_dict(pet) for pet in db.query(Pet).all()]


@router.post("/memory")
def create_memory(payload: MemoryCreate, db: Session = Depends(get_db)) -> dict:
    item = MemoryItem(
        scope=payload.scope,
        kind=payload.kind,
        owner=payload.owner,
        title=payload.title,
        content=payload.content,
        tags=json.dumps(payload.tags),
        source=payload.source,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    log_activity(
        db,
        event_type="memory.created",
        summary=f"Memoria creada: {payload.title}",
        actor=payload.owner,
        source=payload.source,
        action="remember",
        result="success",
        details={"scope": payload.scope, "kind": payload.kind},
    )
    return memory_to_dict(item)


@router.get("/memory")
def list_memory(q: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    if q:
        items = search_memory(db, q)
    else:
        items = db.query(MemoryItem).order_by(MemoryItem.created_at.desc()).limit(100).all()
    return [memory_to_dict(item) for item in items]


@router.get("/memory/search")
def search_memories(q: str, db: Session = Depends(get_db)) -> list[dict]:
    return [memory_to_dict(item) for item in search_memory(db, q)]


@router.delete("/memory/{memory_id}")
def forget_memory(memory_id: int, db: Session = Depends(get_db)) -> dict:
    item = db.get(MemoryItem, memory_id)
    if not item:
        raise HTTPException(status_code=404, detail="memory_not_found")
    title = item.title
    owner = item.owner
    db.delete(item)
    db.commit()
    log_activity(
        db,
        event_type="memory.deleted",
        summary=f"Memoria eliminada: {title}",
        actor=owner,
        source="api",
        action="forget",
        result="success",
        details={"memory_id": memory_id},
    )
    return {"status": "deleted", "id": memory_id}


@router.get("/activity")
def activity(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(100).all()
    result = []
    for row in rows:
        data = row_to_dict(row)
        data["details"] = json.loads(row.details or "{}")
        result.append(data)
    return result


@router.post("/conversations")
def start_conversation(payload: ConversationCreate, db: Session = Depends(get_db)) -> dict:
    session = create_conversation(
        db,
        probable_user=payload.probable_user,
        room_key=payload.room_key,
        voice_point=payload.voice_point,
        confidence=payload.confidence,
    )
    log_activity(
        db,
        event_type="conversation.started",
        summary="Conversation Session iniciada",
        actor=payload.probable_user,
        source="api",
        action="conversation.start",
        result="success",
        details={"conversation_id": session.conversation_id, "room": payload.room_key},
    )
    return row_to_dict(session)


@router.post("/ask")
async def ask(payload: AskRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    return await run_assistant_turn(
        db=db,
        settings=settings,
        text=payload.text,
        conversation_id=payload.conversation_id,
        probable_user=payload.probable_user,
        room_key=payload.room_key,
        source="api",
        provider_factory=OpenAIProvider,
        home_assistant_factory=HomeAssistantClient,
    )


@router.post("/voice/turn")
async def voice_turn(
    file: UploadFile = File(...),
    conversation_id: str | None = Form(default=None),
    probable_user: str | None = Form(default=None),
    room_key: str | None = Form(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Receive a short recording, transcribe it server-side, then use the normal ALI command path."""
    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in SUPPORTED_VOICE_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="unsupported_voice_format")

    audio = await file.read(settings.ali_voice_max_bytes + 1)
    await file.close()
    if not audio:
        raise HTTPException(status_code=400, detail="empty_voice_recording")
    if len(audio) > settings.ali_voice_max_bytes:
        raise HTTPException(status_code=413, detail="voice_recording_too_large")

    provider = OpenAIProvider(settings, db)
    try:
        transcript, transcription_cost = await provider.transcribe_audio(
            filename=file.filename or "ali-voice.webm",
            content_type=content_type,
            audio_bytes=audio,
        )
    except VoiceUnavailableError:
        raise HTTPException(status_code=503, detail="voice_transcription_unavailable") from None
    except BudgetExceededError:
        raise HTTPException(status_code=429, detail="voice_budget_limit") from None
    except LLMProviderError:
        raise HTTPException(status_code=502, detail="voice_transcription_failed") from None

    result = await run_assistant_turn(
        db=db,
        settings=settings,
        text=transcript,
        conversation_id=conversation_id,
        probable_user=probable_user,
        room_key=room_key,
        source="voice",
        include_text_in_log=False,
        provider_factory=OpenAIProvider,
        home_assistant_factory=HomeAssistantClient,
    )
    log_activity(
        db,
        event_type="voice.transcribed",
        summary="Orden de voz recibida y transcrita.",
        actor=probable_user,
        source="voice",
        action="transcribe",
        result="success",
        llm_used=True,
        model=settings.openai_transcription_model,
        estimated_cost=transcription_cost,
        details={"bytes": len(audio), "transcript_retained": False},
    )
    return {
        **result,
        "transcript": transcript,
        "transcription_model": settings.openai_transcription_model,
        "transcription_estimated_cost": transcription_cost,
        "estimated_cost": result["estimated_cost"] + transcription_cost,
    }


@router.post("/voice/speech")
async def voice_speech(
    payload: SpeechRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Optional premium TTS. It is disabled by default; browser speech costs nothing."""
    provider = OpenAIProvider(settings, db)
    try:
        audio, estimated_cost = await provider.synthesize_speech(payload.text)
    except VoiceUnavailableError:
        raise HTTPException(status_code=503, detail="voice_synthesis_unavailable") from None
    except BudgetExceededError:
        raise HTTPException(status_code=429, detail="voice_budget_limit") from None
    except LLMProviderError:
        raise HTTPException(status_code=502, detail="voice_synthesis_failed") from None

    log_activity(
        db,
        event_type="voice.synthesized",
        summary="Respuesta de voz generada.",
        source="voice",
        action="synthesize",
        result="success",
        llm_used=True,
        model=settings.openai_tts_model,
        estimated_cost=estimated_cost,
        details={"characters": len(payload.text), "text_retained": False},
    )
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@router.get("/usage/openai")
def openai_usage(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    now = datetime.now(timezone.utc)
    day_start = now - timedelta(days=1)
    month_start = now - timedelta(days=30)
    day = float(db.query(func.coalesce(func.sum(OpenAIUsage.estimated_cost), 0.0)).filter(OpenAIUsage.created_at >= day_start).scalar() or 0.0)
    month = float(db.query(func.coalesce(func.sum(OpenAIUsage.estimated_cost), 0.0)).filter(OpenAIUsage.created_at >= month_start).scalar() or 0.0)
    return {
        "daily_spend": day,
        "monthly_spend": month,
        "daily_limit": settings.openai_daily_limit,
        "monthly_limit": settings.openai_monthly_limit,
        "soft_monthly_warning": settings.openai_soft_monthly_warning,
        "enabled": settings.openai_enabled,
    }


@router.get("/integrations/homeassistant/health")
async def homeassistant_health(settings: Settings = Depends(get_settings)) -> dict:
    return await HomeAssistantClient(settings).health()

@router.get("/integrations/homeassistant/states/{entity_id}")
async def homeassistant_state(entity_id: str, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return await HomeAssistantClient(settings).get_state(entity_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
