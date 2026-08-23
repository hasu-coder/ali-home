import re


SPORTS = re.compile(
    r"\b(bar[cç]a|barsa|barcelona|real madrid|madrid|atl[eé]tico|f[uú]tbol|futbol|liga|champions|partido|marcador|gol|goles)\b",
    re.IGNORECASE,
)
SPORTS_LIVE_CONTEXT = re.compile(
    r"\b(estoy viendo|estamos viendo|viendo el|c[oó]mo van|cu[aá]nto van|"
    r"qu[ií]en va ganando|resultado|marcador|en qu[eé] minuto|a qu[eé] hora juega|"
    r"cu[aá]ndo juega|d[oó]nde (?:lo )?ponen|ha ganado|han ganado|van ganando|van perdiendo)\b",
    re.IGNORECASE,
)
WEATHER = re.compile(
    r"\b(tiempo|clima|llueve|llover|lluvia|temperatura fuera|calor fuera|fr[ií]o fuera|paraguas|viento)\b",
    re.IGNORECASE,
)
NEWS = re.compile(
    r"\b(noticias|qu[eé] ha pasado|qu[eé] pasa|actualidad|[uú]ltima hora|hoy en las noticias)\b",
    re.IGNORECASE,
)
TRAFFIC = re.compile(
    r"\b(tr[aá]fico|atasco|atascos|carretera|retenciones|cu[aá]nto tardo|cu[aá]nto tardamos)\b",
    re.IGNORECASE,
)
PRICES = re.compile(
    r"\b(precio actual|cu[aá]nto cuesta ahora|a cu[aá]nto est[aá]|cotiza|cotizaci[oó]n|bolsa|bitcoin|euribor)\b",
    re.IGNORECASE,
)
CURRENT_TIME_HINT = re.compile(
    r"\b(ahora|hoy|esta noche|esta tarde|esta ma[nñ]ana|en directo|actual|actualmente|[uú]ltimo|[uú]ltima)\b",
    re.IGNORECASE,
)


def needs_live_context(text: str) -> bool:
    """Return True only when answering well reasonably requires fresh public data.

    Sport-related observations still need a quick reality check: ALI must know
    whether a claimed live match actually exists, but answer it conversationally.
    """
    cleaned = text.strip()
    if not cleaned:
        return False
    # Treat claims about a current match as an unverified premise. ALI should
    # know whether it is real before replying, even if no direct question was asked.
    if SPORTS.search(cleaned) and SPORTS_LIVE_CONTEXT.search(cleaned):
        return True
    if WEATHER.search(cleaned) and CURRENT_TIME_HINT.search(cleaned):
        return True
    if NEWS.search(cleaned):
        return True
    if TRAFFIC.search(cleaned):
        return True
    if PRICES.search(cleaned):
        return True
    return False


def live_context_instruction(text: str) -> str:
    if SPORTS.search(text):
        return (
            "Verifica primero la premisa del usuario con fuentes públicas recientes: determina si el equipo juega ahora, "
            "si ya ha jugado hoy o si no existe partido actual. No inventes ni confirmes una afirmación sin evidencia. "
            "Responde en una sola frase natural para voz: si hay partido, da solo rival y estado/marcador; si no lo hay, "
            "dilo claramente. No incluyas enlaces, citas, alineaciones, crónicas ni un resumen largo."
        )
    if WEATHER.search(text):
        return "Comprueba meteorología actual o prevista pertinente antes de responder."
    if TRAFFIC.search(text):
        return "Comprueba información actual de tráfico/ruta si está disponible antes de responder."
    if PRICES.search(text):
        return "Comprueba el dato/precio/cotización actual y deja claro cuándo se consultó."
    return "Comprueba fuentes públicas recientes y responde con los datos actuales relevantes."
