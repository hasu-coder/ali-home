import json
import re
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.homeassistant.client import HomeAssistantClient
from app.llm.openai_provider import BudgetExceededError, LLMProviderError, OpenAIProvider
from app.llm.router import local_response, needs_remote_llm
from app.models.entities import MemoryItem, UserProfile
from app.services.activity import log_activity
from app.services.conversation import append_turn, create_conversation, get_recent_history
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
    identity = "No se ha identificado a la persona con certeza."
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
        "Por la noche o cuando el contexto indique voz whisper/soft, responde más breve y con tono tranquilo, evitando exclamaciones innecesarias. "
        "Contesta normalmente en una o dos frases para conversación casual, pero amplía cuando una receta, explicación o situación emocional lo necesite. "
        "No cierres con preguntas genéricas, ofrecimientos automáticos ni despedidas de chatbot. Pregunta solo cuando ayude de verdad o falte un dato necesario. "
        "No repitas tu presentación. No afirmes tener conciencia, sentimientos, presencia física ni acceso a datos que no tienes. "
        "No inventes estados de dispositivos, recuerdos, sensores o acciones. Respeta la privacidad y no reveles memoria de otra persona sin permiso."
    )


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
    provider_factory: Callable[[Settings, Session], OpenAIProvider] = OpenAIProvider,
    home_assistant_factory: Callable[[Settings], HomeAssistantClient] = HomeAssistantClient,
) -> dict[str, Any]:
    """Run the single ALI command path used by both typed and spoken requests."""
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
    saved_memory = save_explicit_memory(db, text, probable_user)
    relevant_memory = [memory_to_dict(item) for item in search_memory(db, text, limit=3)]
    if saved_memory:
        relevant_memory.insert(0, memory_to_dict(saved_memory))
    used_remote = False
    model = None
    cost = 0.0
    intent: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None

    if saved_memory:
        response_text = "Vale, lo tendré presente."
        intent = {"intent": "remember", "memory_id": saved_memory.id}
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
            *history_messages,
        ]
        try:
            llm_response = await provider.complete(messages)
            response_text = remove_automatic_follow_up(llm_response.text)
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
        local = local_response(text)
        entity_setting = local.get("entity_setting")
        if entity_setting:
            configured_entity_id = str(getattr(settings, entity_setting, "")).strip()
            if configured_entity_id:
                local["entity_id"] = configured_entity_id
            else:
                # A local order stays local even before its physical device is
                # installed. Do not call Home Assistant with a guessed ID.
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
            "estimated_cost": cost,
            "conversation_id": conversation_id,
            "intent": intent,
            "execution": execution,
            "speech_style": speech_style,
        },
    )
    return {
        "conversation_id": conversation_id,
        "response": response_text,
        "used_remote_llm": used_remote,
        "estimated_cost": cost,
        "intent": intent,
        "execution": execution,
        "speech_style": speech_style,
    }
