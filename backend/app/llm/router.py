import re


def needs_remote_llm(text: str) -> bool:
    """Use the model only when there is no deterministic home intent.

    Checking the parsed intent instead of loose keywords avoids a bad experience:
    a normal conversation that happens to contain the word "cocina" is still a
    conversation, while a request to lower the blinds never reaches OpenAI.
    """
    if not text.strip():
        return False
    return local_response(text).get("intent") == "local_conversation"


def local_response(text: str) -> dict:
    lowered = text.lower()
    air_words = ("aire acondicionado", "climatización", "calefacción", "aire", " ac ")
    has_air_request = any(word in f" {lowered} " for word in air_words)

    if "persiana" in lowered:
        base = {
            "entity_setting": "home_assistant_cover_entity_id",
            "unavailable_response": "Aún no tengo las persianas enlazadas a Home Assistant.",
            "requires_execution": True,
            "domain": "cover",
        }
        if any(word in lowered for word in ("baja", "bajar", "cierra", "cerrar")):
            return {
                **base,
                "intent": "close_blinds",
                "response": "Vale, bajo las persianas.",
                "failure_response": "No he podido bajar las persianas.",
                "service": "close_cover",
                "verify_state": "closed",
            }
        if any(word in lowered for word in ("sube", "subir", "abre", "abrir")):
            return {
                **base,
                "intent": "open_blinds",
                "response": "Vale, subo las persianas.",
                "failure_response": "No he podido subir las persianas.",
                "service": "open_cover",
                "verify_state": "open",
            }
        return {
            "intent": "blinds_direction_needed",
            "response": "Dime si quieres subir o bajar las persianas.",
            "requires_execution": False,
        }

    if has_air_request:
        base = {
            "entity_setting": "home_assistant_climate_entity_id",
            "unavailable_response": "Aún no tengo el aire enlazado a Home Assistant.",
            "requires_execution": True,
            "domain": "climate",
        }
        if any(word in lowered for word in ("apaga", "apagar", "para", "parar", "desconecta")):
            return {
                **base,
                "intent": "turn_off_climate",
                "response": "Vale, apago el aire.",
                "failure_response": "No he podido apagar el aire.",
                "service": "turn_off",
            }
        target_temperature = re.search(r"\b(1[6-9]|2[0-9]|30)\s*(?:º|°|grados?)?\b", lowered)
        if target_temperature and any(word in lowered for word in ("pon", "poner", "ajusta", "ajustar", "temperatura")):
            degrees = int(target_temperature.group(1))
            return {
                **base,
                "intent": "set_climate_temperature",
                "response": f"Vale, dejo el aire a {degrees} grados.",
                "failure_response": "No he podido ajustar la temperatura del aire.",
                "service": "set_temperature",
                "service_data": {"temperature": degrees},
            }
        if any(word in lowered for word in ("enciende", "encender", "pon", "poner", "activa", "activar")):
            return {
                **base,
                "intent": "turn_on_climate",
                "response": "Vale, enciendo el aire.",
                "failure_response": "No he podido encender el aire.",
                "service": "turn_on",
            }
        return {
            "intent": "climate_action_needed",
            "response": "Dime si quieres encenderlo, apagarlo o ajustar una temperatura.",
            "requires_execution": False,
        }

    if "temperatura" in lowered:
        return {
            "intent": "temperature_status_unavailable",
            "response": "Todavía no tengo un termómetro de casa enlazado.",
            "requires_execution": False,
        }
    if "nos vamos" in lowered:
        return {
            "intent": "activate_away_with_pet",
            "response": "Vale, activo el modo ausente con el gato en cuenta.",
            "requires_execution": True,
            "domain": "script",
            "service": "turn_on",
            "entity_id": "script.activate_away_with_pet",
        }
    if "buenas noches" in lowered:
        return {
            "intent": "activate_night_mode",
            "response": "Vale, activo el modo noche.",
            "requires_execution": True,
            "domain": "script",
            "service": "turn_on",
            "entity_id": "script.activate_night_mode",
        }
    if "modo noche" in lowered:
        return {
            "intent": "activate_night_mode",
            "response": "Vale, activo el modo noche.",
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
            "response": "Vale, enciendo la cocina.",
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
        response = "Vale, apago las luces."
        if room == "salon_entresuelo":
            response = "Vale, apago el salón."
        if room == "cocina_salon":
            response = "Vale, apago la cocina."
        return {
            "intent": "set_room_lighting" if room else "set_lighting",
            "room": room,
            "action": "turn_off",
            "state": "off",
            "response": response,
            "failure_response": failure_response,
            "requires_execution": True,
            "domain": "light",
            "service": "turn_off",
            "entity_id": entity_id,
            "verify_state": "off" if room else None,
        }
    return {"intent": "local_conversation", "requires_execution": False}
