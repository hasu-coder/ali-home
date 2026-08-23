# ALI v0.4 — Voz local, identidad y contexto en vivo

## Objetivo

La ruta normal de voz de ALI no paga transcripción:

1. El punto de voz envía un clip corto al ALI Core.
2. `faster-whisper` transcribe en el mini-PC/Codespace.
3. SpeechBrain genera una huella de voz local y la compara con los perfiles enrolados.
4. ALI Core decide si es una orden doméstica, conversación o una frase que necesita información actual.
5. Sólo el razonamiento de texto usa OpenAI cuando está habilitado. La búsqueda web se usa únicamente cuando la frase requiere datos frescos.
6. El audio bruto no se conserva.

## Primera descarga de modelos

La primera transcripción local descarga el modelo Whisper configurado (`small` por defecto). La primera identificación de hablante descarga ECAPA-TDNN. Ambos quedan cacheados en `/app/data/models`, dentro del volumen persistente `ali_data`.

Esto consume espacio y CPU, pero no créditos de OpenAI.

## Enrolar a Ismael y Laura

Conviene grabar al menos 3 muestras por persona, de 4–8 segundos, con frases distintas y desde una distancia normal del micrófono.

Ejemplo desde la máquina donde esté el archivo de audio:

```bash
curl -X POST http://localhost:8000/api/voice/enroll \
  -F username=ismael \
  -F file=@ismael-1.wav
```

Repetir con `ismael-2.wav`, `ismael-3.wav` y después con `laura`.

Consultar estado de perfiles:

```bash
curl http://localhost:8000/api/voice/profiles
```

Sólo se guarda el embedding/huella numérica y el número de muestras; el audio de enrolamiento se descarta.

## Identidad automática

En `/api/voice/turn` una coincidencia local por encima de `ALI_SPEAKER_THRESHOLD` gana sobre cualquier identidad manual enviada por una interfaz de pruebas. En la casa, los puntos de voz no necesitan enviar `probable_user`.

La identificación de voz sirve para personalización y memoria. No debe usarse sola para operaciones de seguridad críticas como abrir cerraduras o desactivar alarmas.

## Contexto en vivo

`needs_live_context()` detecta frases que razonablemente exigen información actual, por ejemplo:

- `Estoy viendo el Barça.`
- `¿Cómo van en el partido?`
- `¿Qué tiempo hace hoy?`
- `¿Hay atasco ahora?`
- `¿Qué ha pasado hoy?`
- `¿A cuánto está el euríbor?`

En esos casos ALI usa una búsqueda web puntual mediante la Responses API, siempre sujeta al presupuesto configurado. Si la consulta falla, ALI debe reconocer que no puede verificar el dato y no inventarlo.

Una conversación histórica como `Cuéntame la historia del FC Barcelona` no activa búsqueda en vivo.

## Coste

- Wake word futuro: local.
- STT normal: local, sin coste de API.
- Identificación Laura/Ismael: local, sin coste de API.
- Home Assistant: local.
- Memoria: local.
- GPT: sólo cuando la conversación lo necesita.
- Web search: sólo para datos actuales.
- OpenAI STT: permanece desactivado y existe únicamente como fallback opcional.

## Prueba web

Cuando `/api/status` informa `local_transcription_available=true`, el botón de voz de la web prioriza `/api/voice/turn` sobre el reconocimiento del navegador. Así se prueba exactamente la ruta que posteriormente usarán los puntos de voz físicos.

El selector Ismael/Laura queda únicamente para mensajes escritos de prueba; los turnos de voz no lo envían.
