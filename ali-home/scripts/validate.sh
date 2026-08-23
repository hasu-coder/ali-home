#!/usr/bin/env sh
set -eu

COMPOSE="docker compose"
BACKEND_URL="${ALI_BACKEND_URL:-http://localhost:8000}"
FRONTEND_URL="${ALI_FRONTEND_URL:-http://localhost:5173}"

pass() {
  printf "%s: PASS\n" "$1"
}

fail() {
  printf "%s: FAIL - %s\n" "$1" "$2"
  exit 1
}

json_check() {
  url="$1"
  pattern="$2"
  body="$(curl -fsS "$url")" || return 1
  printf "%s" "$body" | grep -q "$pattern"
}

printf "ALI HOME - PHASE 1 VALIDATION\n"

command -v docker >/dev/null 2>&1 || fail "Docker" "docker command not found"
pass "Docker"

docker compose version >/dev/null 2>&1 || fail "Docker Compose" "docker compose plugin not available"
pass "Docker Compose"

[ -f .env ] || fail ".env" "create it with: cp .env.example .env"
pass ".env"

$COMPOSE build || fail "Build" "docker compose build failed"
pass "Build"

$COMPOSE up -d || fail "Containers" "docker compose up -d failed"
pass "Containers"

sleep 3

$COMPOSE ps ali-backend | grep -q "Up" || fail "Backend container" "ali-backend is not running"
$COMPOSE ps ali-frontend | grep -q "Up" || fail "Frontend container" "ali-frontend is not running"
pass "Containers active"

json_check "$BACKEND_URL/api/health" '"status":"ok"' || fail "Backend" "GET /api/health did not return status ok"
pass "Backend"

curl -fsS "$FRONTEND_URL/health" >/dev/null || fail "Frontend" "frontend /health not reachable"
pass "Frontend"

json_check "$BACKEND_URL/api/status" '"database":{"status":"ok"' || fail "Database" "database status is not ok"
pass "Database"

json_check "$BACKEND_URL/api/users" '"username":"laura"' || fail "Users" "Laura was not bootstrapped"
json_check "$BACKEND_URL/api/users" '"username":"ismael"' || fail "Users" "Ismael was not bootstrapped"
pass "Users"

json_check "$BACKEND_URL/api/rooms" '"key":"entrada"' || fail "Rooms" "Entrada was not bootstrapped"
json_check "$BACKEND_URL/api/rooms" '"key":"habitacion_bebe"' || fail "Rooms" "Habitacion Bebe was not bootstrapped"
pass "Rooms"

json_check "$BACKEND_URL/api/pets" '"key":"cat"' || fail "Pet" "Cat was not bootstrapped"
pass "Pet"

memory_response="$(curl -fsS -X POST "$BACKEND_URL/api/memory" \
  -H "Content-Type: application/json" \
  -d '{"scope":"shared","kind":"IMPORTANT_MEMORY","owner":"shared","title":"Validation memory","content":"Temporary validation memory for ALI Phase 1.","tags":["validation"],"source":"validate.sh"}')" || fail "Memory" "could not create memory"
memory_id="$(printf "%s" "$memory_response" | sed -n 's/.*"id":\([0-9][0-9]*\).*/\1/p')"
[ -n "$memory_id" ] || fail "Memory" "memory id not found in response"
json_check "$BACKEND_URL/api/memory/search?q=validation" '"Validation memory"' || fail "Memory" "created memory was not searchable"
curl -fsS -X DELETE "$BACKEND_URL/api/memory/$memory_id" >/dev/null || fail "Memory" "could not delete validation memory"
pass "Memory"

json_check "$BACKEND_URL/api/activity" '"action"' || fail "Activity" "activity log does not expose action"
json_check "$BACKEND_URL/api/activity" '"result"' || fail "Activity" "activity log does not expose result"
pass "Activity"

ask_response="$(curl -fsS -X POST "$BACKEND_URL/api/ask" \
  -H "Content-Type: application/json" \
  -d '{"text":"ALI, enciende la cocina","probable_user":"ismael","room_key":"cocina_salon"}')" || fail "Router local" "local ask failed"
printf "%s" "$ask_response" | grep -q '"used_remote_llm":false' || fail "Router local" "known home command used remote LLM"
pass "Router local"

openai_status="$(curl -fsS "$BACKEND_URL/api/usage/openai")" || fail "OpenAI" "usage endpoint failed"
if printf "%s" "$openai_status" | grep -q '"enabled":false'; then
  printf "OpenAI: DISABLED\n"
else
  printf "OpenAI: PASS\n"
fi

ha_status="$(curl -fsS "$BACKEND_URL/api/integrations/homeassistant/health")" || fail "Home Assistant" "health endpoint failed"
if printf "%s" "$ha_status" | grep -q '"enabled":false'; then
  printf "Home Assistant: DISABLED\n"
else
  printf "%s" "$ha_status" | grep -q '"reachable":true' || fail "Home Assistant" "enabled but not reachable"
  printf "Home Assistant: PASS\n"
fi

printf "RESULT: PASS\n"
