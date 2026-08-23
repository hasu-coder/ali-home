import json
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.homeassistant.client import HomeAssistantClient
from app.llm.openai_provider import BudgetExceededError, LLMProviderError, OpenAIProvider
from app.llm.router import local_response, needs_remote_llm
from app.models.entities import UserProfile
from app.services.activity import log_activity
from app.services.conversation import append_turn, create_conversation, get_recent_history
from app.services.memory import memory_to_dict, search_memory


def build_ali_instructions(profile: UserProfile | None) -> str:
    """Stable character guidance plus the authenticated user's durable profile."""
    identity = "No se ha identificado a la persona con certeza."
    if profile:
        identity = (
            f"La persona que habla es {profile.display_name} (usuario: {profile.username}, "
            f"rol: {profile.role}). Reconócelo como {profile.display_name} cuando sea natural."
        )
    return (
        "Eres ALI, la asistente doméstica personal de esta casa. Hablas español de España con un tono "
        "cálido, tranquilo y natural, como una persona de confianza; nunca como un menú ni un robot. "
        f"{identity} "
        "Responde directamente a lo que te han dicho en una o dos frases normalmente. No cierres cada "
        "respuesta con una pregunta ni con ofertas genéricas de ayuda. Haz una sola pregunta solo cuando "
        "necesites un dato imprescindible para responder o actuar. No repitas tu presentación. "
        "No inventes estados de dispositivos, acciones realizadas, recuerdos ni capacidades: si la casa "
        "no está conectada, dilo de forma breve y honesta. Usa la memoria proporcionada solo cuando sea "
        "relevante y no reveles datos privados de otra persona."
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

    relevant_memory = [memory_to_dict(item) for item in search_memory(db, text, limit=5)]
    used_remote = False
    model = None
    cost = 0.0
    intent: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None

    if needs_remote_llm(text):
        provider = provider_factory(settings, db)
        profile = None
        if probable_user:
            profile = db.query(UserProfile).filter_by(username=probable_user).first()
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
                "content": build_ali_instructions(profile),
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
        local = local_response(text)
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
