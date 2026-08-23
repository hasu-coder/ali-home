import json
import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.entities import ConversationSession, utcnow


DEFAULT_TIMEOUT_SECONDS = 90


def create_conversation(
    db: Session,
    *,
    probable_user: str | None,
    room_key: str | None,
    voice_point: str | None,
    confidence: float = 0.0,
) -> ConversationSession:
    now = utcnow()
    session = ConversationSession(
        conversation_id=str(uuid.uuid4()),
        probable_user=probable_user,
        room_key=room_key,
        last_voice_point=voice_point,
        confidence=confidence,
        short_history="[]",
        context=json.dumps({"handoff_ready": True}),
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(seconds=DEFAULT_TIMEOUT_SECONDS),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def append_turn(db: Session, conversation_id: str, speaker: str, text: str) -> ConversationSession | None:
    session = db.query(ConversationSession).filter_by(conversation_id=conversation_id).first()
    if not session:
        return None
    history = json.loads(session.short_history or "[]")
    history.append({"speaker": speaker, "text": text, "at": utcnow().isoformat()})
    session.short_history = json.dumps(history[-12:])
    session.updated_at = utcnow()
    session.expires_at = utcnow() + timedelta(seconds=DEFAULT_TIMEOUT_SECONDS)
    db.commit()
    db.refresh(session)
    return session


def get_recent_history(db: Session, conversation_id: str, limit: int = 8) -> list[dict]:
    session = db.query(ConversationSession).filter_by(conversation_id=conversation_id).first()
    if not session:
        return []
    history = json.loads(session.short_history or "[]")
    return history[-limit:]
