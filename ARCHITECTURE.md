# ALI Home Architecture

## Non-Negotiable Runtime Boundary

Vento is a development tool for ALI, not a runtime dependency.

ALI must run on Laura and Ismael's own local hardware. It must not depend on Vento credits, Vento servers, Vento agents, Vento memory, Vento automations or proprietary Vento infrastructure.

## Phase 1 Runtime

```text
Mini PC local
├── Docker Compose
│   ├── ALI Backend: FastAPI
│   └── ALI Frontend: React/Vite
├── Local database: SQLite initially
├── Home Assistant integration client
├── LLMProvider abstraction
└── OpenAI provider: optional and budget-limited
```

## Control Philosophy

```text
Natural language
↓
ALI Core
↓
Intent router
↓
Deterministic execution layer
↓
Home Assistant
↓
Device state
↓
Verification
↓
ALI response
```

The LLM may reason, summarize and converse. It must not directly execute critical hardware commands.

## Core Modules

- `backend/app/api`: HTTP API.
- `backend/app/models`: database entities.
- `backend/app/services`: memory, activity and conversation services.
- `backend/app/integrations/homeassistant`: Home Assistant API client.
- `backend/app/llm`: provider abstraction, OpenAI implementation and local routing.
- `frontend/src`: ALI Home web UI.

## Memory

Memory is local. OpenAI does not own ALI's memory. Before a remote LLM call, ALI searches local memory and sends only relevant fragments.

Initial memory scopes:

- Ismael
- Laura
- Shared
- House
- Cat
- Experiences
- Temporary

## Conversation Sessions

Conversation sessions store:

- `conversation_id`
- probable user
- room
- last voice point
- confidence
- short history
- timeout

This prepares the future distributed voice handoff system.

## OpenAI Cost Control

Configured through:

- `OPENAI_ENABLED`
- `OPENAI_MODEL`
- `OPENAI_DAILY_LIMIT`
- `OPENAI_MONTHLY_LIMIT`
- `OPENAI_SOFT_MONTHLY_WARNING`
- `OPENAI_INPUT_COST_PER_1M`
- `OPENAI_OUTPUT_COST_PER_1M`

Known local intents bypass OpenAI entirely.

