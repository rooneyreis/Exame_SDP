#!/usr/bin/env bash
# Scenario 13: NETWORK failure (the node keeps running, but is unreachable):
#   A) partition AFTER both shards prepared -> decision COMMIT is durable -> the recovery
#      loop finishes it when the network comes back (money is not lost).
#   B) partition BEFORE America prepares    -> America cannot vote -> ABORTADA, Europa is
#      rolled back (money never leaves the account).
source "$(dirname "$0")/lib.sh"

NET=gss_globalnet
cut_network()     { cmd "docker network disconnect $NET pg-america"; docker network disconnect "$NET" pg-america; ok "pg-america isolado da rede (o processo continua vivo)"; }
restore_network() { cmd "docker network connect --ip 172.28.0.63 --alias pg-america.global.local $NET pg-america"
                    docker network connect --ip 172.28.0.63 --alias pg-america.global.local "$NET" pg-america; ok "rede reposta"; }
trap 'docker network connect --ip 172.28.0.63 --alias pg-america.global.local "$NET" pg-america 2>/dev/null || true' EXIT

title "Cenário 13 — Partição de rede durante o 2PC"
login carla.mendes@cliente.test "$CLIENT_PASSWORD"
FROM=GS-EU-00000003; TO=GS-AM-00000001

# ------------------------------------------------------------------------- A
step "A1. Partição DEPOIS do PREPARE: pausa de 15 s antes da decisão"
chaos '{"pause_after_prepare": 15}'
B_FROM=$(balance $FROM); B_TO=$(balance $TO)
OUT=$(mktemp)
curl -s --cacert "$CA" -X POST "$BASE/transfers" -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -H "Idempotency-Key: demo13a-$(date +%s%N)" -d "{\"from_iban\":\"$FROM\",\"to_iban\":\"$TO\",\"amount\":\"30.00\"}" \
  -w '\n%{http_code}' > "$OUT" &
CURL_PID=$!
sleep 4
prepared_xacts
cut_network
wait $CURL_PID
LAST_STATUS=$(tail -1 "$OUT"); LAST_BODY=$(head -n -1 "$OUT")
TX=$(echo "$LAST_BODY" | jq -r .tx_id)
info "resposta: HTTP $LAST_STATUS  state=$(echo "$LAST_BODY" | jq -r .state)"
timeline
[[ "$(echo "$LAST_BODY" | jq -r .state)" == DECISAO_COMMIT ]] && ok "decisão gravada; COMMIT na América pendente" || fail "esperava DECISAO_COMMIT"
info "durante a partição a América continua a ter a transação preparada:"
docker exec pg-america psql -U postgres -d bank -tAc "SELECT gid FROM pg_prepared_xacts" | sed 's/^/    /'
pause

step "A2. Repor a rede → o recovery loop conclui"
restore_network
wait_tx_state "$TX" CONFIRMADA 60 || fail "não concluiu"
timeline
A_FROM=$(balance $FROM); A_TO=$(balance $TO)
info "$FROM: $B_FROM → $A_FROM EUR    $TO: $B_TO → $A_TO USD"
decimal_true "D('$B_FROM') - 30 == D('$A_FROM') and D('$B_TO') + D('32.40') == D('$A_TO')" && ok "−30.00 EUR / +32.40 USD: o dinheiro saiu e entrou" || fail "saldos errados"
pause

# ------------------------------------------------------------------------- B
step "B1. Partição ANTES do PREPARE da América: pausa de 8 s antes da fase 1"
chaos '{"off": true}'
chaos '{"pause_before_prepare": 8}'
B_FROM=$(balance $FROM)
curl -s --cacert "$CA" -X POST "$BASE/transfers" -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -H "Idempotency-Key: demo13b-$(date +%s%N)" -d "{\"from_iban\":\"$FROM\",\"to_iban\":\"$TO\",\"amount\":\"40.00\"}" \
  -w '\n%{http_code}' > "$OUT" &
CURL_PID=$!
sleep 3
cut_network
wait $CURL_PID
LAST_STATUS=$(tail -1 "$OUT"); LAST_BODY=$(head -n -1 "$OUT")
info "resposta: HTTP $LAST_STATUS  state=$(echo "$LAST_BODY" | jq -r .state)"
info "motivo: $(echo "$LAST_BODY" | jq -r .failure_reason)"
timeline
[[ "$(echo "$LAST_BODY" | jq -r .state)" == ABORTADA ]] && ok "a América não votou → ABORTADA; a Europa fez ROLLBACK" || fail "esperava ABORTADA"
A_FROM=$(balance $FROM)
decimal_true "D('$B_FROM') == D('$A_FROM')" && ok "saldo de $FROM inalterado ($A_FROM EUR): o dinheiro não saiu" || fail "dinheiro saiu!"
restore_network
pause

step "C. Verificação final"
chaos '{"off": true}'
sleep 3
prepared_xacts
check_consistency

title "Cenário 13 concluído"
