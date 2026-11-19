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

STAFF_PASSWORD="Staff#2026"
CLIENT_PASSWORD="Cliente#2026"
