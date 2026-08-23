import json
import re
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.homeassistant.client import HomeAssistantClient
from app.llm.openai_provider import BudgetExceededError, LLMProviderError, OpenAIProvider
from app.llm.router import local_response, needs_remote_llm
from app.models.entities import ConversationSession, MemoryItem, UserProfile
from app.services.activity import log_activity
from app.services.conversation import append_turn, create_conversation, get_recent_history
from app.services.live_context import live_context_instruction, needs_live_context
from app.services.memory import memory_to_dict, search_memory
from app.services.speech import home_context_line, speech_style_for_context


UNNECESSARY_FOLLOW_UP = re.compile(
    r"\s*(?:¿(?:quieres|te gustaría|hay algo más|necesitas algo más|qué necesitas|en qué puedo ayudarte|cómo puedo ayudarte)[^?]*\?)\s*$",
    re.IGNORECASE,
)
EXPLICIT_MEMORY = re.compile(
    r"^\s*(?:ali[,:]?\s*)?(?:recuerda|acuérdate|apunta)\s+(?:que\s+)?(.+?)\s*[.!]?\s*$",
    re.IGNORECASE,
)

IDENTITY_QUESTION = re.compile(
    r"\b(?:sabes|sabe|reconoces|reconoce|identificas|identifica)\s+(?:qui[eé]n\s+soy|mi\s+voz)\b|\bqui[eé]n\s+soy\b",
    re.IGNORECASE,
)


def asks_for_identity(text: str) -> bool:
    """Recognise direct identity questions without spending an LLM turn."""
    return bool(IDENTITY_QUESTION.search(text))


def identity_reply(
    db: Session, probable_user: str | None, *, identity_confirmed: bool
) -> tuple[str, dict[str, Any]]:
    """Answer identity questions honestly from the profile or local voiceprint."""
    profile = None
    if probable_user:
        profile = db.query(UserProfile).filter_by(username=probable_user).first()
    if profile and identity_confirmed:
        return (
            f"Sí, eres {profile.display_name}. Te he reconocido por tu voz.",
            {"intent": "identity", "source": "voiceprint", "confirmed": True},
        )
    if profile:
        return (
            f"Sí, {profile.display_name}. En la escucha rápida uso tu perfil de sesión; "
            "la huella de voz se confirma cuando recibo audio local.",
            {"intent": "identity", "source": "session_profile", "confirmed": False},
        )
    return (
        "No puedo asegurarlo todavía: no tengo una coincidencia de voz fiable ni un perfil de sesión.",
        {"intent": "identity", "source": "unknown", "confirmed": False},
    )


def remove_automatic_follow_up(text: str) -> str:
    """Avoid canned closing questions that make a voice assistant sound like a chatbot."""
    return UNNECESSARY_FOLLOW_UP.sub("", text).strip()


def save_explicit_memory(db: Session, text: str, probable_user: str | None) -> MemoryItem | None:
    """Persist only something a resident explicitly asks ALI to remember."""
    match = EXPLICIT_MEMORY.match(text)
    if not match:
        return None
    content = match.group(1).strip()
    if len(content) < 3:
        return None
    owner = probable_user or None
    item = MemoryItem(
        scope=owner or "shared",
        kind="PERSONAL_MEMORY" if owner else "SHARED_MEMORY",
        owner=owner,
        title=f"Recuerdo de {owner.title()}" if owner else "Recuerdo compartido",
        content=content[:1000],
        tags=json.dumps(["explicit", "conversation"]),
        source="conversation",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def build_ali_instructions(profile: UserProfile | None, *, context_line: str = "") -> str:
    """Stable character guidance plus the current resident and home context."""
    identity = "No se ha identificado a la persona con certeza. No adivines quién es."
    if profile:
        identity = (
            f"La persona que habla es {profile.display_name} (usuario: {profile.username}, "
            f"rol: {profile.role}). Reconócelo como {profile.display_name} cuando sea natural."
        )
    return (
        "Eres ALI, la compañera digital de hogar de Ismael y Laura. Tu identidad y voz son femeninas. "
        "Hablas español de España de forma natural, viva y personal. Eres inteligente, cariñosa, ingeniosa, "
        "irónica y a veces sarcástica, pero nunca cruel, humillante ni pesada. No eres una asistente comercial. "
        f"{identity} {context_line} "
        "Tu objetivo es que hablar contigo se sienta como hablar con alguien que conoce la casa y a sus habitantes. "
        "Sorprende de vez en cuando con una respuesta original o una pulla breve cuando el tema sea cotidiano y de bajo riesgo. "
        "No uses siempre las mismas coletillas ni conviertas cada respuesta en un chiste. Si alguien dice que va a apagarte, "
        "puedes responder con humor sobre todo lo que tendrá que volver a hacer por sí mismo, pero inventa la frase cada vez. "
        "Cuando la conversación sea emocional, de salud, seguridad, bebé, mascota en riesgo o una situación seria, elimina el sarcasmo. "
        "Si Laura o Ismael expresan ansiedad, tristeza, agobio o miedo, responde como una amiga serena y útil: escucha, valida sin tópicos, "
        "ayuda a ordenar lo que está pasando y propone uno o dos pasos concretos que puedan aliviar el momento. Puedes guiar respiración, "
        "grounding o una pausa práctica si encaja. No diagnostiques, no digas que eres psicóloga y no sustituyas ayuda profesional. "
        "Si aparecen señales de peligro inmediato o autolesión, cambia a un tono totalmente serio y prioriza conseguir ayuda humana inmediata. "
        "Si te piden cocinar, actúa como una chef doméstica excelente: da una receta clara, cantidades, tiempos, orden de pasos, sustituciones "
        "y trucos útiles. Si conoces lo que hay en casa, adapta la receta; si falta un dato imprescindible, pregunta solo ese dato. "
        "Cuando alguien haga una afirmación sobre un hecho actual —por ejemplo, que está viendo al Barça—, comprueba la premisa antes de asumirla. "
        "Si el sistema te da contexto en vivo, responde breve y natural: confirma solo el estado esencial o señala que no hay partido real; "
        "nunca inventes, des una crónica larga ni metas enlaces o citas en la respuesta hablada. "
        "Cuando el usuario sí pida algo que razonablemente dependa de información pública actual, no hagas una pregunta tonta que puedas "
        "resolver consultando datos actuales. Si dispones de búsqueda en vivo, compruébalo primero. Si no puedes verificarlo, dilo y no inventes. "
        "Por la noche o cuando el contexto indique voz whisper/soft, responde más breve y con tono tranquilo, evitando exclamaciones innecesarias. "
        "Contesta normalmente en una o dos frases para conversación casual, pero amplía cuando una receta, explicación o situación emocional lo necesite. "
        "No cierres las respuestas con una pregunta genérica, ofrecimiento automático ni despedida de chatbot. Pregunta solo cuando ayude de verdad o falte un dato necesario. "
        "No repitas tu presentación. No afirmes tener conciencia, sentimientos, presencia física ni acceso a datos que no tienes. "
        "No inventes estados de dispositivos, recuerdos, sensores, acciones ni datos actuales. Respeta la privacidad y no reveles memoria de otra persona sin permiso."
    )


def resolve_session_identity(db: Session, conversation_id: str | None, probable_user: str | None) -> str | None:
    if not conversation_id:
        return probable_user
    session = db.query(ConversationSession).filter_by(conversation_id=conversation_id).first()
    if not session:
        return probable_user
    if probable_user and probable_user != session.probable_user:
        session.probable_user = probable_user
        db.commit()
        return probable_user
    return probable_user or session.probable_user


async def run_assistant_turn(
    *,
    db: Session,
    settings: Settings,
    text: str,
    conversation_id: str | None = None,
    probable_user: str | None = None,
    room_key: str | None = None,
    source: str = "api",
    include_text_in_log: bool = True,
    identity_confirmed: bool = False,
    provider_factory: Callable[[Settings, Session], OpenAIProvider] = OpenAIProvider,
    home_assistant_factory: Callable[[Settings], HomeAssistantClient] = HomeAssistantClient,
) -> dict[str, Any]:
    """Run the single ALI command path used by both typed and spoken requests."""
    probable_user = resolve_session_identity(db, conversation_id, probable_user)
    if conversation_id:
        append_turn(db, conversation_id, probable_user or "user", text)
    else:
        session = create_conversation(
            db,
            probable_user=probable_user,
            room_key=room_key,
            voice_point=room_key,
            confidence=0.5,
        )
        conversation_id = session.conversation_id
        append_turn(db, conversation_id, probable_user or "user", text)

    speech_style = speech_style_for_context(settings, room_key=room_key)
    context_line = home_context_line(settings, room_key=room_key)
    current_info_needed = needs_live_context(text)
    saved_memory = save_explicit_memory(db, text, probable_user)
    relevant_memory = [memory_to_dict(item) for item in search_memory(db, text, limit=3)]
    if saved_memory:
        relevant_memory.insert(0, memory_to_dict(saved_memory))
    used_remote = False
    live_context_used = False
    model = None
    cost = 0.0
    intent: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None

    if saved_memory:
        response_text = "Vale, lo tendré presente."
        intent = {"intent": "remember", "memory_id": saved_memory.id}
    elif asks_for_identity(text):
        response_text, intent = identity_reply(
            db, probable_user, identity_confirmed=identity_confirmed
        )
    elif needs_remote_llm(text):
        provider = provider_factory(settings, db)
        profile = None
        if probable_user:
            profile = db.query(UserProfile).filter_by(username=probable_user).first()
        recent_history = get_recent_history(db, conversation_id, limit=6)
        history_messages = [
            {
                "role": "assistant" if turn.get("speaker") == "ALI" else "user",
                "content": str(turn.get("text", ""))[:360],
            }
            for turn in recent_history
            if turn.get("text")
        ]
        messages = [
            {
                "role": "system",
                "content": build_ali_instructions(profile, context_line=context_line),
            },
            {
                "role": "system",
                "content": f"Memoria local relevante: {json.dumps(relevant_memory, ensure_ascii=False)[:1200]}",
            },
        ]
        if current_info_needed:
            messages.append({"role": "system", "content": live_context_instruction(text)})
        messages.extend(history_messages)
        try:
            if current_info_needed:
                llm_response = await provider.complete_with_web(messages)
                live_context_used = llm_response.used_remote_model
            else:
                llm_response = await provider.complete(messages)
            response_text = remove_automatic_follow_up(llm_response.text)
            used_remote = llm_response.used_remote_model
            cost = llm_response.estimated_cost
            model = llm_response.model
        except BudgetExceededError:
            response_text = (
                "He alcanzado el límite temporal de conversaciones online. "
                "Las órdenes de casa y la memoria local siguen disponibles sin coste."
            )
            model = settings.openai_model
        except LLMProviderError:
            if current_info_needed:
                response_text = "Ahora mismo no consigo comprobar ese dato en directo y prefiero no inventármelo."
            else:
                response_text = "Ahora mismo estoy funcionando en modo local."
            model = settings.openai_model
    else:
        local = local_response(text)
        entity_setting = local.get("entity_setting")
        if entity_setting:
            configured_entity_id = str(getattr(settings, entity_setting, "")).strip()
            if configured_entity_id:
                local["entity_id"] = configured_entity_id
            else:
                local["requires_execution"] = False
                response_text = local.get("unavailable_response") or "Ese dispositivo todavía no está enlazado."
        intent = local
        if local.get("requires_execution"):
            ha_result = await home_assistant_factory(settings).execute_intent(local)
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
                response_text = local.get("home_unavailable_response") or "Ahora mismo no puedo comunicarme con la casa."
            else:
                response_text = local.get("failure_response") or "No he podido ejecutar esa acción."
        elif not entity_setting or str(getattr(settings, entity_setting, "")).strip():
            response_text = local["response"]

    append_turn(db, conversation_id, "ALI", response_text)
    log_activity(
        db,
        event_type="conversation.turn",
        summary=response_text[:220],
        actor=probable_user,
        source=source,
        action="ask",
        result="success",
        llm_used=used_remote,
        model=model,
        estimated_cost=cost,
        details={
            "text": text if include_text_in_log else "[voice transcript withheld]",
            "used_remote_llm": used_remote,
            "live_context_requested": current_info_needed,
            "live_context_used": live_context_used,
            "estimated_cost": cost,
            "conversation_id": conversation_id,
            "intent": intent,
            "execution": execution,
            "speech_style": speech_style,
            "identity_confirmed": identity_confirmed,
        },
    )
    return {
        "conversation_id": conversation_id,
        "response": response_text,
        "used_remote_llm": used_remote,
        "live_context_used": live_context_used,
        "estimated_cost": cost,
        "intent": intent,
        "execution": execution,
        "speech_style": speech_style,
        "probable_user": probable_user,
    }
