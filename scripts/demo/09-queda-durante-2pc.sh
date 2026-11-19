#!/usr/bin/env bash
# Scenario 09: a shard goes down DURING a 2PC, after both shards prepared.
# The coordinator decides COMMIT, Europa commits, America is unreachable -> the decision is
# durable, so the recovery loop keeps retrying and finishes when pg-america comes back.
source "$(dirname "$0")/lib.sh"

title "Cenário 09 — Queda de um shard durante o 2PC"
FROM=GS-EU-00000002; TO=GS-AM-00000003
B_FROM=$(balance $FROM); B_TO=$(balance $TO)
info "saldos antes: $FROM=$B_FROM EUR   $TO=$B_TO USD"

step "1. Ativar pausa de 20 s depois do PREPARE (antes da decisão)"
chaos '{"pause_after_prepare": 20}'

step "2. O Bruno inicia a transferência (em segundo plano)"
login bruno.costa@cliente.test "$CLIENT_PASSWORD"
KEY="demo09-$(date +%s%N)"
OUT=$(mktemp)
curl -s --cacert "$CA" -X POST "$BASE/transfers" -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -H "Idempotency-Key: $KEY" -d "{\"from_iban\":\"$FROM\",\"to_iban\":\"$TO\",\"amount\":\"200.00\"}" \
  -w '\n%{http_code}' > "$OUT" &
CURL_PID=$!
sleep 4
info "os dois shards já votaram SIM e mantêm as transações preparadas (com os locks):"
prepared_xacts
pause

step "3. Derrubar o pg-america enquanto o coordenador ainda não decidiu"
cmd "docker stop pg-america"; docker stop pg-america >/dev/null
ok "pg-america parado (a réplica continua, mas só aceita leituras)"
info "à espera do fim da pausa..."
wait $CURL_PID
LAST_STATUS=$(tail -1 "$OUT"); LAST_BODY=$(head -n -1 "$OUT")
info "resposta: HTTP $LAST_STATUS  state=$(echo "$LAST_BODY" | jq -r .state)"
TX=$(echo "$LAST_BODY" | jq -r .tx_id)
timeline
[[ "$(echo "$LAST_BODY" | jq -r .state)" == DECISAO_COMMIT ]] && ok "decisão COMMIT gravada; Europa fez commit, América pendente" || fail "esperava DECISAO_COMMIT"
pause

step "4. Enquanto o pg-america está em baixo, o recovery loop tenta com backoff exponencial"
sleep 6
docker logs --since 15s coordinator 2>&1 | grep -m3 'recovery: shard AM' | jq -r .msg 2>/dev/null | sed 's/^/    /' || true
info "a transação preparada continua guardada no disco do pg-america (pg_twophase), à espera"

step "5. Voltar a ligar o pg-america"
cmd "docker start pg-america"; docker start pg-america >/dev/null
wait_healthy pg-america
info "a aguardar o recovery loop..."
wait_tx_state "$TX" CONFIRMADA 60 || fail "a transação não foi concluída"
ok "recovery fez COMMIT PREPARED no pg-america → CONFIRMADA"
timeline
pause

step "6. Verificação: sem dinheiro perdido"
chaos '{"off": true}'
A_FROM=$(balance $FROM); A_TO=$(balance $TO)
info "$FROM: $B_FROM → $A_FROM EUR    $TO: $B_TO → $A_TO USD"
decimal_true "D('$B_FROM') - 200 == D('$A_FROM') and D('$B_TO') + 216 == D('$A_TO')" && ok "−200.00 EUR / +216.00 USD" || fail "saldos errados"
prepared_xacts
check_consistency

title "Cenário 09 concluído"
