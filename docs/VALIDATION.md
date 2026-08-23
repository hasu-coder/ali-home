# ALI Home Phase 1 Validation

Run these commands outside Vento on the target mini PC or a development machine with Docker.

## 1. Prepare Configuration

```bash
cd ali-home
cp .env.example .env
```

Open `.env` and keep OpenAI and Home Assistant disabled for the first validation unless you are ready to test them:

```env
OPENAI_ENABLED=false
HOME_ASSISTANT_ENABLED=false
```

## 2. Build And Start

```bash
docker compose up --build -d
```

## 3. Run Validation Script

```bash
./scripts/validate.sh
```

Expected shape:

```text
ALI HOME - PHASE 1 VALIDATION
Docker: PASS
Docker Compose: PASS
.env: PASS
Build: PASS
Containers: PASS
Containers active: PASS
Backend: PASS
Frontend: PASS
Database: PASS
Users: PASS
Rooms: PASS
Pet: PASS
Memory: PASS
Activity: PASS
Router local: PASS
OpenAI: DISABLED
Home Assistant: DISABLED
RESULT: PASS
```

## 4. Manual Checks

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/status
curl http://localhost:8000/api/users
curl http://localhost:8000/api/rooms
curl http://localhost:8000/api/pets
curl http://localhost:8000/api/activity
```

Open the UI:

```text
http://localhost:5173
```

## 5. Persistence Check

Create a memory through the API or UI, then restart containers without deleting volumes:

```bash
docker compose down
docker compose up -d
curl "http://localhost:8000/api/memory/search?q=validation"
```

Data should remain because SQLite lives in the `ali_data` Docker volume.

Do not run `docker compose down -v` unless you intentionally want to delete ALI's local database volume.
