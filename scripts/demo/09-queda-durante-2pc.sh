#!/usr/bin/env bash
# Scenario 09: a shard goes down DURING a 2PC, after both shards prepared.
# The coordinator decides COMMIT, Europa commits, America is unreachable -> the decision is
# durable. Meanwhile the copy of America (on pg-africa) takes over: the prepared transaction
# is there (synchronous replication), so the recovery loop commits it on the copy.
# pg-america comes back later and takes its role back.
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
ok "pg-america parado"
SECS=$(wait_role pg-africa 5433 f 40) || fail "a cópia da América não assumiu o papel"
ok "a cópia da América em pg-africa:5433 assumiu o papel em ${SECS}s"
info "a transação preparada também está na cópia (chegou lá antes de o pg-america cair):"
docker exec pg-africa psql -U postgres -p 5433 -tAc "SELECT gid FROM pg_prepared_xacts" | sed 's/^/    /'
info "à espera do fim da pausa..."
wait $CURL_PID
LAST_STATUS=$(tail -1 "$OUT"); LAST_BODY=$(head -n -1 "$OUT")
info "resposta: HTTP $LAST_STATUS  state=$(echo "$LAST_BODY" | jq -r .state)"
TX=$(echo "$LAST_BODY" | jq -r .tx_id)
timeline
state=$(echo "$LAST_BODY" | jq -r .state)
[[ "$state" == DECISAO_COMMIT || "$state" == CONFIRMADA ]] && ok "decisão COMMIT gravada; Europa fez commit" || fail "esperava DECISAO_COMMIT"
pause

step "4. O recovery loop conclui o COMMIT na cópia da América, sem esperar pelo pg-america"
wait_tx_state "$TX" CONFIRMADA 60 || fail "a transação não foi concluída"
ok "COMMIT PREPARED feito na cópia (pg-africa:5433) → CONFIRMADA, com o pg-america ainda em baixo"
timeline
pause

step "5. Voltar a ligar o pg-america: sincroniza-se e retoma o seu papel"
cmd "docker start pg-america"; docker start pg-america >/dev/null
wait_all_home || fail "a topologia não voltou ao normal"
topology
ok "pg-america é de novo o primário da América, com a transação confirmada"
pause

step "6. Verificação: sem dinheiro perdido"
chaos '{"off": true}'
A_FROM=$(balance $FROM); A_TO=$(balance $TO)
info "$FROM: $B_FROM → $A_FROM EUR    $TO: $B_TO → $A_TO USD"
decimal_true "D('$B_FROM') - 200 == D('$A_FROM') and D('$B_TO') + 216 == D('$A_TO')" && ok "−200.00 EUR / +216.00 USD" || fail "saldos errados"
prepared_xacts
check_consistency

title "Cenário 09 concluído"
