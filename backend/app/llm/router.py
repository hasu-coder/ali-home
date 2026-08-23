LOCAL_INTENT_KEYWORDS = {
    "enciende",
    "apaga",
    "luz",
    "luces",
    "persiana",
    "persianas",
    "temperatura",
    "modo",
    "cocina",
    "salón",
    "dormitorio",
    "nos vamos",
    "buenas noches",
}


def needs_remote_llm(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    if any(keyword in lowered for keyword in LOCAL_INTENT_KEYWORDS):
        return False
    # Natural conversation can be short ("¿qué puedes hacer?"). Only known
    # deterministic home intents bypass the LLM, so ALI does not sound stuck.
    return True


def local_response(text: str) -> dict:
    lowered = text.lower()
    if "nos vamos" in lowered:
        return {
            "intent": "activate_away_with_pet",
            "response": "Preparando modo ausente con gato.",
            "requires_execution": True,
            "domain": "script",
            "service": "turn_on",
            "entity_id": "script.activate_away_with_pet",
        }
    if "buenas noches" in lowered:
        return {
            "intent": "activate_night_mode",
            "response": "Modo noche preparado.",
            "requires_execution": True,
            "domain": "script",
            "service": "turn_on",
            "entity_id": "script.activate_night_mode",
        }
    if "modo noche" in lowered:
        return {
            "intent": "activate_night_mode",
            "response": "Modo noche preparado.",
            "requires_execution": True,
            "domain": "script",
            "service": "turn_on",
            "entity_id": "script.activate_night_mode",
        }
    if "enciende" in lowered and "cocina" in lowered:
        return {
            "intent": "set_room_lighting",
            "room": "cocina_salon",
            "action": "turn_on",
            "state": "on",
            "response": "Listo.",
            "failure_response": "No he podido encender la cocina.",
            "requires_execution": True,
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.cocina_salon",
            "verify_state": "on",
        }
    if "apaga" in lowered:
        room = None
        entity_id = "all"
        failure_response = "No he podido apagar las luces."
        if "salón" in lowered or "salon" in lowered:
            room = "salon_entresuelo"
            entity_id = "light.salon_entresuelo"
            failure_response = "No he podido apagar el salón."
        if "cocina" in lowered:
            room = "cocina_salon"
            entity_id = "light.cocina_salon"
            failure_response = "No he podido apagar la cocina."
        return {
            "intent": "set_room_lighting" if room else "set_lighting",
            "room": room,
            "action": "turn_off",
            "state": "off",
            "response": "Listo.",
            "failure_response": failure_response,
            "requires_execution": True,
            "domain": "light",
            "service": "turn_off",
            "entity_id": entity_id,
            "verify_state": "off" if room else None,
        }
    return {"intent": "local_conversation", "response": "Estoy en modo local. Puedo ayudarte con la casa y comandos básicos.", "requires_execution": False}
