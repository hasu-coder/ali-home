import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.integrations.homeassistant.client import HomeAssistantClient
from app.llm.openai_provider import BudgetExceededError, LLMProviderError, OpenAIProvider
from app.llm.router import local_response, needs_remote_llm
from app.models.entities import ActivityLog, ConversationSession, MemoryItem, OpenAIUsage, Pet, Room, UserProfile
from app.services.activity import log_activity
from app.services.conversation import append_turn, create_conversation, get_recent_history
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
    conversation_id = payload.conversation_id
    if conversation_id:
        append_turn(db, conversation_id, payload.probable_user or "user", payload.text)
    else:
        session = create_conversation(
            db,
            probable_user=payload.probable_user,
            room_key=payload.room_key,
            voice_point=payload.room_key,
            confidence=0.5,
        )
        conversation_id = session.conversation_id
        append_turn(db, conversation_id, payload.probable_user or "user", payload.text)

    relevant_memory = [memory_to_dict(item) for item in search_memory(db, payload.text, limit=5)]
    used_remote = False
    model = None
    cost = 0.0
    intent: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    if needs_remote_llm(payload.text):
        provider = OpenAIProvider(settings, db)
        recent_history = get_recent_history(db, conversation_id, limit=8)
        history_messages = [
            {
                "role": "assistant" if turn.get("speaker") == "ALI" else "user",
                "content": str(turn.get("text", "")),
            }
            for turn in recent_history
            if turn.get("text")
        ]
        messages = [
            {
                "role": "system",
                "content": (
                    "Eres ALI, Asistente de Laura e Ismael. Responde en español, breve, natural y sin inventar "
                    "estados de dispositivos."
                ),
            },
            {"role": "system", "content": f"Memoria local relevante: {json.dumps(relevant_memory, ensure_ascii=False)}"},
            *history_messages,
        ]
        try:
            llm_response = await provider.complete(messages)
            response_text = llm_response.text
            used_remote = llm_response.used_remote_model
            cost = llm_response.estimated_cost
            model = llm_response.model
        except BudgetExceededError as exc:
            response_text = f"Estoy en modo local: {exc}."
            model = settings.openai_model
        except LLMProviderError:
            response_text = "Ahora mismo estoy funcionando en modo local."
            model = settings.openai_model
    else:
        local = local_response(payload.text)
        intent = local
        if local.get("requires_execution"):
            ha_result = await HomeAssistantClient(settings).execute_intent(local)
            execution = {
                "success": ha_result.success,
                "verified": ha_result.verified,
                "state": ha_result.state,
                "error": ha_result.error,
                "status_code": ha_result.status_code,
            }
            if ha_result.success:
                response_text = local["response"]
            elif ha_result.error == "home_assistant_disabled":
                response_text = "Ahora mismo no puedo comunicarme con la casa."
            else:
                response_text = local.get("failure_response") or "No he podido ejecutar esa acción."
        else:
            response_text = local["response"]

    append_turn(db, conversation_id, "ALI", response_text)
    log_activity(
        db,
        event_type="conversation.turn",
        summary=response_text[:220],
        actor=payload.probable_user,
        source="voice_or_api",
        action="ask",
        result="success",
        llm_used=used_remote,
        model=model,
        estimated_cost=cost,
        details={
            "text": payload.text,
            "used_remote_llm": used_remote,
            "estimated_cost": cost,
            "conversation_id": conversation_id,
            "intent": intent,
            "execution": execution,
        },
    )
    return {
        "conversation_id": conversation_id,
        "response": response_text,
        "used_remote_llm": used_remote,
        "estimated_cost": cost,
        "intent": intent,
        "execution": execution,
    }


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
