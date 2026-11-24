#!/usr/bin/env bash
# Shared helpers for the demo scripts. Usage: source "$(dirname "$0")/lib.sh"
#
# Every demo prints what it does, calls the API through nginx with curl (TLS verified
# by the local CA), and saves its output to docs/evidencias/<demo>.log.
# PAUSE=1 ./scripts/demo/01-registo-login.sh  -> waits for Enter between steps (live demo)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASE=${BASE:-https://localhost}
CA=infra/certs/ca.crt
EVIDENCE_DIR=docs/evidencias
DEMO_NAME=${DEMO_NAME:-$(basename "$0" .sh)}
mkdir -p "$EVIDENCE_DIR"

# Screen gets colours; the evidence file gets the same text without colour codes.
exec > >(tee >(sed -u -r 's/\x1b\[[0-9;]*m//g' > "$EVIDENCE_DIR/$DEMO_NAME.log")) 2>&1

title() { printf '\n\033[1;36m══════ %s ══════\033[0m\n' "$*"; echo "($(date -u +%Y-%m-%dT%H:%M:%SZ))"; }
step()  { printf '\n\033[1;33m▶ %s\033[0m\n' "$*"; }
info()  { printf '  %s\n' "$*"; }
ok()    { printf '\033[1;32m  ✔ %s\033[0m\n' "$*"; }
fail()  { printf '\033[1;31m  ✘ %s\033[0m\n' "$*"; exit 1; }
cmd()   { printf '\033[0;90m  $ %s\033[0m\n' "$*"; }
pause() { if [[ "${PAUSE:-0}" == "1" ]]; then read -rp "  (Enter para continuar)" _ </dev/tty; fi; }

TOKEN=""
LAST_STATUS=""
LAST_BODY=""
LAST_SERVED=""
EXTRA_HEADERS=()

# api METHOD PATH [JSON]  -> sets LAST_STATUS, LAST_BODY, LAST_SERVED (uses $TOKEN if set)
api() {
  local method=$1 path=$2 data=${3:-}
  local headers body
  headers=$(mktemp); body=$(mktemp)
  local args=(-s -X "$method" --cacert "$CA" -D "$headers" -o "$body" -w '%{http_code}'
              -H 'content-type: application/json' --max-time 30)
  [[ -n "$TOKEN" ]] && args+=(-H "Authorization: Bearer $TOKEN")
  [[ -n "$data" ]] && args+=(-d "$data")
  for h in "${EXTRA_HEADERS[@]+"${EXTRA_HEADERS[@]}"}"; do args+=(-H "$h"); done
  LAST_STATUS=$(curl "${args[@]}" "$BASE$path" || echo 000)
  LAST_BODY=$(cat "$body")
  LAST_SERVED=$(grep -i '^x-served-by:' "$headers" | awk '{print $2}' | tr -d '\r' || true)
  rm -f "$headers" "$body"
  printf '\033[0;90m  %s %s -> HTTP %s%s\033[0m\n' "$method" "$path" "$LAST_STATUS" "${LAST_SERVED:+ (X-Served-By: $LAST_SERVED)}"
}

# show [jq filter]: pretty-prints the last response body
show() { echo "$LAST_BODY" | jq "${1:-.}" 2>/dev/null | sed 's/^/    /' || echo "    $LAST_BODY"; }

expect() {  # expect STATUS "description"
  if [[ "$LAST_STATUS" == "$1" ]]; then ok "$2 (HTTP $1)"; else show; fail "$2: esperado HTTP $1, obtido $LAST_STATUS"; fi
}

# login EMAIL PASSWORD -> sets TOKEN
login() {
  TOKEN=""
  api POST /auth/login "{\"email\":\"$1\",\"password\":\"$2\"}"
  [[ "$LAST_STATUS" == "200" ]] || { show; fail "login de $1 falhou (HTTP $LAST_STATUS)"; }
  TOKEN=$(echo "$LAST_BODY" | jq -r .access_token)
}

# jwt_claims TOKEN: decodes the JWT payload (base64url) — no verification, just to show it
jwt_claims() {
  local payload
  payload=$(echo "$1" | cut -d. -f2 | tr '_-' '/+')
  while (( ${#payload} % 4 )); do payload="$payload="; done
  echo "$payload" | base64 -d 2>/dev/null | jq . | sed 's/^/    /'
}

# sql "conninfo" "SQL": runs SQL directly on a Postgres node (over TLS, from globalnet)
sql() {
  cmd "psql \"$1\" -c \"$2\""
  docker compose run --rm -T pgclient "$1 sslmode=verify-full" -c "$2" 2>/dev/null | sed 's/^/    /'
}

wait_healthy() {  # wait_healthy CONTAINER
  for _ in $(seq 1 60); do
    [[ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null)" == "healthy" ]] && { ok "$1 está healthy"; return 0; }
    sleep 1
  done
  fail "$1 não ficou healthy"
}

# decimal_true "D('10.00') - 5 == D('5.00')": exact decimal arithmetic (no float rounding)
decimal_true() { python3 -c "from decimal import Decimal as D; import sys; sys.exit(0 if ($1) else 1)"; }

STAFF_PASSWORD="Staff#2026"
CLIENT_PASSWORD="Cliente#2026"

# --- transfers / 2PC helpers (Phase 4) ---------------------------------------------

# transfer FROM_IBAN TO_IBAN AMOUNT IDEMPOTENCY_KEY  (as the client in $TOKEN)
transfer() {
  EXTRA_HEADERS=("Idempotency-Key: $4")
  api POST /transfers "{\"from_iban\":\"$1\",\"to_iban\":\"$2\",\"amount\":\"$3\"}"
  EXTRA_HEADERS=()
}

# timeline: prints the tx_events of the transaction in $LAST_BODY
timeline() {
  echo "$LAST_BODY" | jq -r '.events[] | "    \(.at | tostring | .[11:23])  \(.event)\(if .detail then "   " + (.detail | tostring) else "" end)"'
}

# as ROLE_EMAIL: run the following api call with another identity, then restore $TOKEN
with_user() {  # with_user EMAIL PASSWORD METHOD PATH [JSON]
  local saved=$TOKEN
  login "$1" "$2" >/dev/null
  api "$3" "$4" "${5:-}"
  TOKEN=$saved
}

chaos() {  # chaos '{"pause_after_prepare": 20}' | chaos '{"off": true}'
  with_user admin@globalscale.test "$STAFF_PASSWORD" POST /admin/chaos "$1"
  [[ "$LAST_STATUS" == 200 ]] || fail "chaos falhou"
  info "chaos no coordenador: $(echo "$LAST_BODY" | jq -c .)"
}

check_consistency() {
  with_user auditor@globalscale.test "$STAFF_PASSWORD" GET /admin/consistency
  echo "$LAST_BODY" | jq -c '{ok, checked_transactions, confirmed, aborted, in_progress, prepared_xacts, problems}' | sed 's/^/    /'
  [[ "$(echo "$LAST_BODY" | jq -r .ok)" == "true" ]] && ok "/admin/consistency OK: sem dinheiro perdido nem duplicado" \
    || fail "inconsistência detetada"
}

balance() {  # balance IBAN -> prints the balance (read with the operator's identity)
  local saved=$TOKEN saved_status=$LAST_STATUS saved_body=$LAST_BODY
  login operador@globalscale.test "$STAFF_PASSWORD" >/dev/null 2>&1
  local b
  b=$(curl -s --cacert "$CA" -H "Authorization: Bearer $TOKEN" "$BASE/accounts/$1" | jq -r .balance)
  TOKEN=$saved; LAST_STATUS=$saved_status; LAST_BODY=$saved_body
  echo "$b"
}

prepared_xacts() {  # shows pg_prepared_xacts in every shard
  for n in pg-europa pg-america pg-africa; do
    local out
    out=$(docker exec "$n" psql -U postgres -d bank -tAc "SELECT gid || '  (preparada às ' || to_char(prepared, 'HH24:MI:SS') || ')' FROM pg_prepared_xacts" 2>/dev/null || echo "(nó em baixo)")
    info "$n: ${out:-nenhuma}"
  done
}

wait_tx_state() {  # wait_tx_state TX_ID STATE TIMEOUT
  for _ in $(seq 1 "$3"); do
    api GET "/transfers/$1" >/dev/null
    [[ "$(echo "$LAST_BODY" | jq -r .state)" == "$2" ]] && return 0
    sleep 1
  done
  return 1
}

# --- ring of copies (common/topology.json) ------------------------------------------

topology() {  # prints where each database is and which location is the primary
  ./scripts/topologia.sh | sed 's/^/    /'
}

db_role() {  # db_role NODE PORT -> f (primary) | t (copy/standby) | "" (down)
  docker exec "$1" psql -U postgres -p "$2" -tAc "SELECT pg_is_in_recovery()" 2>/dev/null || true
}

wait_role() {  # wait_role NODE PORT f|t TIMEOUT -> prints the seconds it took
  local t0=$(date +%s)
  for _ in $(seq 1 "$4"); do
    [[ "$(db_role "$1" "$2")" == "$3" ]] && { echo $(( $(date +%s) - t0 )); return 0; }
    sleep 1
  done
  return 1
}

wait_all_home() {  # every database back on its owner node, every copy following it
  for _ in $(seq 1 90); do
    [[ "$(db_role pg-core 5432)$(db_role pg-europa 5432)$(db_role pg-america 5432)$(db_role pg-africa 5432)" == ffff &&
       "$(db_role pg-america 5434)$(db_role pg-america 5433)$(db_role pg-africa 5433)$(db_role pg-europa 5433)" == tttt ]] && return 0
    sleep 2
  done
  return 1
}
