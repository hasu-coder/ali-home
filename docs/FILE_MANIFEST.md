# ALI Home File Manifest

## Root

- `README.md`: project overview, local-first rule and quick start.
- `ARCHITECTURE.md`: Phase 1 architecture and non-negotiable runtime boundary.
- `INSTALL.md`: installation, validation, backup and restore notes.
- `.env.example`: safe runtime configuration template without secrets.
- `.gitignore`: excludes secrets, databases, caches and build artifacts.
- `docker-compose.yml`: portable Docker runtime with `ali-backend`, `ali-frontend` and persistent `ali_data` volume.

## Backend

- `backend/Dockerfile`: FastAPI container build.
- `backend/requirements.txt`: pinned Python runtime/test dependencies.
- `backend/app/main.py`: FastAPI app, CORS, startup bootstrap and router registration.
- `backend/app/core/config.py`: environment-based settings.
- `backend/app/db/session.py`: SQLAlchemy engine, session and SQLite data path preparation.
- `backend/app/models/entities.py`: users, rooms, pet, memory, Activity, conversations and OpenAI usage tables.
- `backend/app/api/routes.py`: health, status, users, rooms, pets, memory, Activity, conversations, OpenAI usage and Home Assistant endpoints.
- `backend/app/services/bootstrap.py`: idempotent first boot seed for Laura, Ismael, rooms and Cat.
- `backend/app/services/activity.py`: local Activity logging service.
- `backend/app/services/conversation.py`: Conversation Session manager.
- `backend/app/services/memory.py`: local memory serialization and search.
- `backend/app/llm/provider.py`: provider-neutral `LLMProvider` contract.
- `backend/app/llm/openai_provider.py`: optional OpenAI implementation with token/cost logging and budget checks.
- `backend/app/llm/router.py`: local intent routing for known home commands.
- `backend/app/integrations/homeassistant/client.py`: optional Home Assistant API client.
- `backend/tests/test_api.py`: Phase 1 backend test suite.

## Frontend

- `frontend/Dockerfile`: React/Vite build served by Nginx.
- `frontend/nginx.conf`: static frontend, `/health`, and `/api` proxy to `ali-backend`.
- `frontend/package.json`: frontend scripts and dependencies.
- `frontend/package-lock.json`: reproducible npm dependency lock.
- `frontend/vite.config.ts`: Vite configuration.
- `frontend/index.html`: app HTML entry.
- `frontend/src/main.tsx`: ALI Home dashboard UI.
- `frontend/src/api/client.ts`: frontend API client.
- `frontend/src/styles/app.css`: ALI Home visual styling.
- `frontend/src/vite-env.d.ts`: Vite TypeScript declarations.

## Scripts And Docs

- `scripts/validate.sh`: Linux/macOS validation script for mini PC execution.
- `scripts/dev.sh`: local development helper.
- `docs/PHASE_1.md`: Phase 1 implementation notes.
- `docs/VALIDATION.md`: commands and expected validation output.
- `docs/FILE_MANIFEST.md`: this manifest.

## Reserved Directories

- `voice/`: reserved for later local wake word, STT and TTS services.
- `memory/`: reserved for later advanced memory/RAG modules.
- `presence/`: reserved for later presence fusion services.
- `safety/`: reserved for later local Safety Core.
- `integrations/homeassistant/`: reserved for non-backend Home Assistant integration assets.
- `config/`: reserved for versioned non-secret configuration templates.
- `docker/`: reserved for future Docker support files.
- `tests/`: reserved for cross-service tests.
