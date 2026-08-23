# ALI Home

ALI, Asistente de Laura e Ismael, is a local-first home intelligence system.

**Vento is a development tool for ALI, not a runtime dependency.** ALI is designed to run on Laura and Ismael's own hardware. The code, memory, configuration, automations, database and integrations must remain portable outside Vento.

## Phase 1 Scope

This repository currently contains the first executable foundation:

- FastAPI backend.
- SQLite local database by default.
- Laura and Ismael local user profiles.
- Initial room model.
- Cat model.
- Local memory system.
- Conversation Session manager.
- Activity Log.
- Home Assistant integration client.
- `LLMProvider` abstraction.
- OpenAI provider with daily and monthly budget limits.
- Local intent router so simple home commands do not call GPT.
- Secure browser-to-backend voice turn: OpenAI transcription is optional and the API key never reaches the frontend.
- Fast browser speech for local commands, with optional fixed OpenAI TTS for natural conversations.
- Initial ALI Home frontend.
- Docker Compose runtime.
- Validation script for running Phase 1 outside Vento.

## Quick Start

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- Frontend: <http://localhost:5173>
- Backend health: <http://localhost:8000/api/health>

Run the external validation checklist:

```bash
./scripts/validate.sh
```

## Configuration

Secrets must stay in `.env`, never in Git.

```env
ALI_TEXT_PROVIDER=hetzner
HETZNER_INFERENCE_API_KEY=
HETZNER_INFERENCE_BASE_URL=https://inference.hetzner.com/api/v1
HETZNER_INFERENCE_MODEL=Qwen/Qwen3.6-35B-A3B-FP8
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
OPENAI_ENABLED=false
OPENAI_MONTHLY_LIMIT=2.00
OPENAI_DAILY_LIMIT=0.10
OPENAI_VOICE_ENABLED=false
OPENAI_TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
OPENAI_TTS_ENABLED=false
OPENAI_TTS_VOICE=coral
OPENAI_TTS_SPEED=1.2
HOME_ASSISTANT_URL=http://homeassistant.local:8123
HOME_ASSISTANT_TOKEN=
HOME_ASSISTANT_ENABLED=false
HOME_ASSISTANT_COVER_ENTITY_ID=
HOME_ASSISTANT_CLIMATE_ENTITY_ID=
```

## Runtime Rule

ALI follows:

```text
ALI understands
The house executes
ALI verifies
ALI responds
```

The LLM must not directly control critical hardware. Natural language is converted into normalized intents. Home Assistant executes deterministic automations and device actions. ALI verifies state before claiming completion whenever the device exposes state.

## Local-First Cost Rule

Known commands such as "enciende la cocina", "baja las persianas" and "pon el aire a 22 grados" are handled locally and never call a remote model. They are only sent to Home Assistant after their configured entity ID is known; before that, ALI says plainly that the device is not linked.

For normal open conversation, set `ALI_TEXT_PROVIDER=hetzner` and add a Hetzner Inference API token to the backend-only `.env`. Qwen then replaces OpenAI chat with an estimated cost of zero inside ALI. Hetzner's API does not include web search, transcription or text-to-speech, so ALI never claims it has checked current information unless a separate verified data source is configured.

The web interface first uses the browser's speech recognition, so it consumes no OpenAI credit. If that browser feature is unavailable, the optional short-audio transcription endpoint is the compatibility fallback and its estimated OpenAI cost is logged. On the future home mini-PC, both wake-word detection and transcription can be local. OpenAI TTS is called only for open conversations, never for deterministic home-command acknowledgements.

## Voice setup (cheap default)

Set the API key only in the server-side `.env` or a Codespaces secret—never in frontend variables or Git. Then enable only transcription:

```env
OPENAI_VOICE_ENABLED=true
OPENAI_ENABLED=false
OPENAI_TTS_ENABLED=false
```

This enables the short-audio fallback for browsers without speech recognition. The normal web route uses browser recognition first, and local home commands answer with the browser's quick voice at no OpenAI cost. Turn on `OPENAI_TTS_ENABLED=true` only when you want ALI's natural fixed voice for open conversations; it also counts against the same daily and monthly budget. `OPENAI_TTS_SPEED=1.2` is the default agile pace.

## Persistence

Docker Compose stores ALI's SQLite database in the `ali_data` Docker volume mounted at `/app/data` inside `ali-backend`. Recreating containers does not delete users, rooms, memories, conversations, Activity or usage records unless the Docker volume is explicitly removed.
