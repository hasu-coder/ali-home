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
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
OPENAI_ENABLED=false
OPENAI_MONTHLY_LIMIT=5.00
OPENAI_DAILY_LIMIT=1.00
HOME_ASSISTANT_URL=http://homeassistant.local:8123
HOME_ASSISTANT_TOKEN=
HOME_ASSISTANT_ENABLED=false
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

Known commands such as "enciende la cocina" are handled locally and do not call GPT. GPT is only used for advanced conversation or reasoning. All usage is logged with estimated cost and checked against configurable budgets.

## Persistence

Docker Compose stores ALI's SQLite database in the `ali_data` Docker volume mounted at `/app/data` inside `ali-backend`. Recreating containers does not delete users, rooms, memories, conversations, Activity or usage records unless the Docker volume is explicitly removed.
