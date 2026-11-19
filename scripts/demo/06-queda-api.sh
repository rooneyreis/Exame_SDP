#!/usr/bin/env bash
# Scenario 06: api-1 goes down -> nginx sends everything to api-2 -> api-1 comes back.
source "$(dirname "$0")/lib.sh"

title "Cenário 06 — Queda de uma instância da API"
login ana.silva@cliente.test "$CLIENT_PASSWORD"

served() { # served N -> sends N requests, prints who answered, fails on any non-200
  local seen=()
  for _ in $(seq 1 "$1"); do
    api GET /accounts
    [[ "$LAST_STATUS" == 200 ]] || fail "pedido falhou com HTTP $LAST_STATUS"
    seen+=("$LAST_SERVED")
  done
  SERVED=$(printf '%s\n' "${seen[@]}" | sort | uniq -c | awk '{printf "%s×%s ", $1, $2}')
}

step "1. Situação normal: o nginx distribui os pedidos (round-robin)"
served 4
ok "respostas: $SERVED"
[[ "$SERVED" == *api-1* && "$SERVED" == *api-2* ]] || fail "esperava as duas instâncias"
pause

step "2. Derrubar a api-1"
STOPPED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
cmd "docker stop api-1"; docker stop api-1 >/dev/null
ok "api-1 parada"
served 6
ok "todos os pedidos responderam 200: $SERVED"
[[ "$SERVED" != *api-1* ]] || fail "api-1 não devia responder"
info "logs do nginx: o 1.º pedido tentou a api-1 (172.28.0.11), falhou e foi repetido na api-2 (172.28.0.12);"
info "depois disso a api-1 fica marcada em baixo durante fail_timeout=10s e nem é tentada:"
docker logs --since "$STOPPED_AT" nginx 2>&1 | grep -E '"upstream":"172.28.0.11:8000, 172.28.0.12:8000"|upstream timed out|connect\(\) failed'   | head -3 | sed 's/^/    /' || true
pause

step "3. Voltar a ligar a api-1"
cmd "docker start api-1"; docker start api-1 >/dev/null
wait_healthy api-1
sleep 10   # fail_timeout=10s: nginx volta a tentar a api-1 depois deste tempo
served 6
ok "respostas: $SERVED"
[[ "$SERVED" == *api-1* ]] || fail "api-1 devia voltar a receber pedidos"

title "Cenário 06 concluído: nenhum pedido falhou"
