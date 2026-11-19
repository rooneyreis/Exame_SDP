#!/usr/bin/env bash
# Scenario 10: the coordinator process dies right AFTER writing DECISAO_COMMIT and BEFORE
# the COMMIT PREPARED. Docker restarts it (restart: unless-stopped); on start-up the
# recovery loop reads the durable decision and commits the prepared transactions.
source "$(dirname "$0")/lib.sh"

title "Cenário 10 — Crash do coordenador depois da decisão"
FROM=GS-AM-00000001; TO=GS-EU-00000002
B_FROM=$(balance $FROM); B_TO=$(balance $TO)
info "saldos antes: $FROM=$B_FROM USD   $TO=$B_TO EUR"

step "1. Ativar crash_after_decision"
chaos '{"crash_after_decision": true}'
RESTARTS=$(docker inspect -f '{{.RestartCount}}' coordinator)

step "2. O David transfere 50.00 USD para o Bruno — o coordenador morre a meio"
login david.smith@cliente.test "$CLIENT_PASSWORD"
KEY="demo10-$(date +%s%N)"
transfer $FROM $TO 50.00 "$KEY"
show
TX=$(echo "$LAST_BODY" | jq -r .tx_id)
[[ "$LAST_STATUS" == 503 ]] && ok "a api respondeu 503 mas devolveu o tx_id ($TX)" || fail "esperava 503"
info "logs do coordenador antes de morrer:"
docker logs coordinator 2>&1 | grep -E 'CHAOS|DECISAO_COMMIT' | tail -2 | jq -r '.msg' 2>/dev/null | sed 's/^/    /' || true
info "transações preparadas à espera de decisão:"
prepared_xacts
pause

step "3. O Docker reinicia o coordenador sozinho"
for _ in $(seq 1 30); do
  [[ "$(docker inspect -f '{{.RestartCount}}' coordinator)" -gt "$RESTARTS" ]] && break; sleep 1
done
ok "RestartCount: $RESTARTS → $(docker inspect -f '{{.RestartCount}}' coordinator)"
wait_healthy coordinator

step "4. O recovery loop encontra DECISAO_COMMIT no log e conclui a transação"
wait_tx_state "$TX" CONFIRMADA 30 || fail "não foi concluída"
timeline
ok "CONFIRMADA pela recuperação (RECUPERACAO_COMMIT_*)"
pause

step "5. O cliente repete o pedido com a mesma Idempotency-Key: não há segundo débito"
transfer $FROM $TO 50.00 "$KEY"
info "HTTP $LAST_STATUS  state=$(echo "$LAST_BODY" | jq -r .state)  idempotent_replay=$(echo "$LAST_BODY" | jq -r .idempotent_replay)"
A_FROM=$(balance $FROM); A_TO=$(balance $TO)
info "$FROM: $B_FROM → $A_FROM USD    $TO: $B_TO → $A_TO EUR"
decimal_true "D('$B_FROM') - 50 == D('$A_FROM') and D('$B_TO') + D('46.30') == D('$A_TO')" && ok "−50.00 USD / +46.30 EUR, uma única vez" || fail "saldos errados"
info "chaos depois do reinício (estado em memória, volta a off):"
with_user admin@globalscale.test "$STAFF_PASSWORD" GET /health >/dev/null
check_consistency

title "Cenário 10 concluído"
