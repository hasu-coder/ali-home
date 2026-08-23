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
from app.models.entities import ActivityLog, ConversationSession, MemoryItem, OpenAIUsage, Pet, Room, UserProfile, VoiceProfile
from app.services.activity import log_activity
from app.services.assistant import run_assistant_turn
from app.services.conversation import create_conversation
from app.services.local_voice import LocalVoiceEngine, LocalVoiceUnavailableError, local_voice_dependencies
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
    style: str = Field(default="normal", pattern="^(normal|soft|whisper)$")


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


def local_voice_status(settings: Settings) -> dict:
    deps = local_voice_dependencies()
    local_stt_available = settings.ali_local_stt_enabled and deps["faster_whisper"]
    speaker_available = (
        settings.ali_speaker_id_enabled
        and deps["faster_whisper"]
        and deps["speechbrain"]
        and deps["torch"]
    )
    cloud_stt_available = bool(settings.openai_voice_enabled and settings.openai_api_key)
    return {
        "transcription_available": bool(local_stt_available or cloud_stt_available),
        "local_transcription_available": bool(local_stt_available),
        "local_transcription_model": settings.ali_local_stt_model,
        "cloud_transcription_available": cloud_stt_available,
        "speaker_identification_available": bool(speaker_available),
        "speaker_threshold": settings.ali_speaker_threshold,
        "tts_available": bool(settings.openai_tts_enabled and settings.openai_api_key),
        "max_seconds": settings.ali_voice_max_seconds,
        "transcription_model": (
            f"local:{settings.ali_local_stt_model}" if local_stt_available else settings.openai_transcription_model
        ),
    }


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
            "voice_profiles": db.query(VoiceProfile).count(),
        },
        "openai": {
            "enabled": settings.openai_enabled,
            "configured": bool(settings.openai_api_key),
            "live_context_enabled": settings.openai_live_context_enabled,
        },
        "voice": local_voice_status(settings),
        "home_assistant": home_assistant,
    }


@router.get("/config/public")
def public_config(settings: Settings = Depends(get_settings)) -> dict:
    voice = local_voice_status(settings)
    return {
        "wake_word": settings.ali_wake_word,
        "language": settings.ali_language,
        "openai_enabled": settings.openai_enabled,
        "openai_monthly_limit": settings.openai_monthly_limit,
        "openai_soft_monthly_warning": settings.openai_soft_monthly_warning,
        "live_context_enabled": settings.openai_live_context_enabled,
        "voice_transcription_available": voice["transcription_available"],
        "voice_local_transcription_available": voice["local_transcription_available"],
        "voice_speaker_identification_available": voice["speaker_identification_available"],
        "voice_tts_available": voice["tts_available"],
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


async def read_voice_upload(file: UploadFile, settings: Settings) -> tuple[bytes, str]:
    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in SUPPORTED_VOICE_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="unsupported_voice_format")
    audio = await file.read(settings.ali_voice_max_bytes + 1)
    await file.close()
    if not audio:
        raise HTTPException(status_code=400, detail="empty_voice_recording")
    if len(audio) > settings.ali_voice_max_bytes:
        raise HTTPException(status_code=413, detail="voice_recording_too_large")
    return audio, content_type


@router.post("/voice/enroll")
async def voice_enroll(
    file: UploadFile = File(...),
    username: str = Form(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Enroll one local voice sample. Raw audio is discarded after embedding."""
    audio, _ = await read_voice_upload(file, settings)
    engine = LocalVoiceEngine(settings)
    try:
        profile = await engine.enroll_async(db, username=username.strip().lower(), audio_bytes=audio)
    except ValueError:
        raise HTTPException(status_code=404, detail="unknown_user") from None
    except LocalVoiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    log_activity(
        db,
        event_type="voice.enrolled",
        summary=f"Muestra de voz local añadida para {profile.username}.",
        actor=profile.username,
        source="voice",
        action="speaker.enroll",
        result="success",
        details={"sample_count": profile.sample_count, "audio_retained": False},
    )
    return {
        "username": profile.username,
        "sample_count": profile.sample_count,
        "model": profile.model,
        "audio_retained": False,
    }


@router.get("/voice/profiles")
def voice_profiles(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "username": profile.username,
            "sample_count": profile.sample_count,
            "model": profile.model,
            "active": profile.active,
            "updated_at": profile.updated_at,
        }
        for profile in db.query(VoiceProfile).order_by(VoiceProfile.username).all()
    ]


@router.post("/voice/turn")
async def voice_turn(
    file: UploadFile = File(...),
    conversation_id: str | None = Form(default=None),
    probable_user: str | None = Form(default=None),
    room_key: str | None = Form(default=None),
    duration_seconds: float | None = Form(default=None, ge=0.0, le=120.0),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Local-first voice turn: local STT + local speaker ID, paid STT only as fallback."""
    original_filename = file.filename or "ali-voice.webm"
    audio, content_type = await read_voice_upload(file, settings)
    engine = LocalVoiceEngine(settings)

    transcript = ""
    transcription_cost = 0.0
    transcription_model = f"local:{settings.ali_local_stt_model}"
    transcription_source = "local"
    local_error: str | None = None

    if settings.ali_local_stt_enabled:
        try:
            transcript = await engine.transcribe_async(audio)
        except LocalVoiceUnavailableError as exc:
            local_error = str(exc)

    if not transcript:
        provider = OpenAIProvider(settings, db)
        try:
            transcript, transcription_cost = await provider.transcribe_audio(
                filename=original_filename,
                content_type=content_type,
                audio_bytes=audio,
                duration_seconds=duration_seconds,
            )
            transcription_model = settings.openai_transcription_model
            transcription_source = "openai_fallback"
        except VoiceUnavailableError:
            raise HTTPException(status_code=503, detail=local_error or "voice_transcription_unavailable") from None
        except BudgetExceededError:
            raise HTTPException(status_code=429, detail="voice_budget_limit") from None
        except LLMProviderError:
            raise HTTPException(status_code=502, detail="voice_transcription_failed") from None

    detected_user: str | None = None
    speaker_similarity = 0.0
    speaker_identified = False
    if settings.ali_speaker_id_enabled:
        try:
            match = await engine.identify_async(db, audio)
            detected_user = match.username
            speaker_similarity = match.similarity
            speaker_identified = match.accepted
        except LocalVoiceUnavailableError:
            pass

    # The browser/manual identity is only a development fallback. A confident
    # local voiceprint always wins, so household use does not need a selector.
    resolved_user = detected_user or probable_user

    result = await run_assistant_turn(
        db=db,
        settings=settings,
        text=transcript,
        conversation_id=conversation_id,
        probable_user=resolved_user,
        room_key=room_key,
        source="voice",
        include_text_in_log=False,
        provider_factory=OpenAIProvider,
        home_assistant_factory=HomeAssistantClient,
    )
    log_activity(
        db,
        event_type="voice.transcribed",
        summary="Voz recibida, transcrita y atribuida localmente cuando fue posible.",
        actor=resolved_user,
        source="voice",
        action="transcribe",
        result="success",
        llm_used=transcription_source == "openai_fallback",
        model=transcription_model,
        estimated_cost=transcription_cost,
        details={
            "bytes": len(audio),
            "duration_seconds": duration_seconds,
            "transcript_retained": False,
            "transcription_source": transcription_source,
            "speaker_identified": speaker_identified,
            "speaker_similarity": speaker_similarity,
            "speaker": detected_user,
        },
    )
    return {
        **result,
        "transcript": transcript,
        "transcription_model": transcription_model,
        "transcription_source": transcription_source,
        "transcription_estimated_cost": transcription_cost,
        "speaker": detected_user,
        "speaker_confidence": speaker_similarity,
        "speaker_identified": speaker_identified,
        "estimated_cost": result["estimated_cost"] + transcription_cost,
    }


@router.post("/voice/speech")
async def voice_speech(
    payload: SpeechRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Optional premium TTS. Local/browser speech remains the free default."""
    provider = OpenAIProvider(settings, db)
    try:
        audio, estimated_cost = await provider.synthesize_speech(payload.text, style=payload.style)
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
        details={"characters": len(payload.text), "text_retained": False, "style": payload.style},
    )
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@router.get("/usage/openai")
def openai_usage(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    now = datetime.now(timezone.utc)
    day_start = now - timedelta(days=1)
    month_start = now - timedelta(days=30)
    day = float(db.query(func.coalesce(func.sum(OpenAIUsage.estimated_cost), 0.0)).filter(OpenAIUsage.created_at >= day_start).scalar() or 0.0)
    month = float(db.query(func.coalesce(func.sum(OpenAIUsage.estimated_cost), 0.0)).filter(OpenAIUsage.created_at >= month_start).scalar() or 0.0)
    by_model = {
        str(model): float(cost or 0.0)
        for model, cost in db.query(OpenAIUsage.model, func.sum(OpenAIUsage.estimated_cost))
        .filter(OpenAIUsage.created_at >= month_start)
        .group_by(OpenAIUsage.model)
        .all()
    }
    return {
        "daily_spend": day,
        "monthly_spend": month,
        "daily_limit": settings.openai_daily_limit,
        "monthly_limit": settings.openai_monthly_limit,
        "soft_monthly_warning": settings.openai_soft_monthly_warning,
        "enabled": settings.openai_enabled,
        "monthly_by_model": by_model,
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
