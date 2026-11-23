#!/usr/bin/env bash
# Scenario 17: África totally down (primary AND replica). A transfer to an África account is
# not refused: the money is kept in custody in another active shard, with where it came from
# and where it was going. The owner can use it meanwhile. When África is back, the remaining
# amount and the history are forwarded there automatically.
source "$(dirname "$0")/lib.sh"

title "Cenário 17 — Região em baixo: valor em custódia noutro nó e reencaminhamento automático"
N=$(date +%s%N | tail -c 8)
AF1=GS-AF-00000001
EU1=GS-EU-00000001
CORE="host=pg-core.global.local dbname=coordinator"
EU_SHARD="host=pg-europa.global.local,pg-europa-replica.global.local target_session_attrs=read-write dbname=bank"

start_africa() {
  docker start pg-africa >/dev/null
  for _ in $(seq 1 60); do
    [[ "$(docker exec pg-africa psql -U postgres -tAc 'SELECT pg_is_in_recovery()' 2>/dev/null)" == f ]] && break; sleep 2
  done
  docker start pg-africa-replica >/dev/null
}
trap start_africa EXIT     # África always comes back, even if a step fails

step "1. Antes: saldo da conta $AF1 (Amina, África) e diretório de contas no pg-core"
AF_BEFORE=$(balance $AF1)
info "saldo em África: $AF_BEFORE MZN"
for _ in $(seq 1 30); do
  [[ "$(docker compose run --rm -T pgclient "$CORE sslmode=verify-full" -tAc "SELECT 1 FROM account_directory WHERE iban = '$AF1'" 2>/dev/null)" == 1 ]] && break
  sleep 2
done
sql "$CORE" "SELECT iban, region, currency, status FROM account_directory WHERE iban = '$AF1'"
ok "a conta está no diretório: pode ser validada mesmo com a região em baixo"
pause

step "2. Derrubar África por completo (primário E réplica)"
cmd "docker stop pg-africa pg-africa-replica"; docker stop pg-africa pg-africa-replica >/dev/null
ok "região África totalmente indisponível"
pause

step "3. A Ana (Europa) transfere 10.00 EUR para $AF1"
login ana.silva@cliente.test "$CLIENT_PASSWORD"
transfer $EU1 $AF1 10.00 "demo17-in-$N"
expect 201 "transferência confirmada apesar de África estar em baixo"
show '{state, routing, kind, from_region, to_region, debit_region, credit_region, amount, converted_amount, to_currency}'
timeline
TX_IN=$(echo "$LAST_BODY" | jq -r .tx_id)
CREDITED=$(echo "$LAST_BODY" | jq -r .converted_amount)
[[ "$(echo "$LAST_BODY" | jq -r .routing)" == CUSTODIA ]] && ok "routing=CUSTODIA: o crédito ficou em custódia no shard $(echo "$LAST_BODY" | jq -r .credit_region)" || fail "esperava CUSTODIA"
sql "$EU_SHARD" "SELECT target_iban, target_region, currency, balance FROM custody_accounts WHERE target_iban = '$AF1'"
pause

step "4. A Amina vê o valor retido e pode usá-lo"
login amina.mussa@cliente.test "$CLIENT_PASSWORD"
api GET /accounts
expect 200 "contas da Amina"
echo "$LAST_BODY" | jq -c ".[] | select(.iban == \"$AF1\") | {iban, balance, currency, region_unavailable, held_in}" | sed 's/^/    /'
transfer $AF1 $EU1 100.00 "demo17-out-$N"
expect 201 "transferiu 100.00 MZN a partir do valor retido"
show '{state, routing, kind, debit_region, credit_region}'
transfer $AF1 $EU1 "$CREDITED" "demo17-too-much-$N"
expect 422 "não pode gastar mais do que o valor retido"
show '{state, failure_reason}'
with_user operador@globalscale.test "$STAFF_PASSWORD" POST /accounts/$AF1/withdraw '{"amount":"5.00"}'
expect 200 "levantamento de 5.00 MZN ao balcão, também do valor retido"
show '{balance, custody_region}'
api GET /accounts/$AF1/movements
info "movimentos em custódia (ainda por reencaminhar):"
echo "$LAST_BODY" | jq -r '.[] | "    \(.type)  \(.amount) \(.currency)  \(.origin)  via \(.via_region)  contraparte \(.counterparty // "-")"'
pause

step "5. África volta: o coordenador reencaminha o saldo restante e o histórico"
cmd "docker start pg-africa pg-africa-replica"; start_africa; trap - EXIT
EXPECTED=$(python3 -c "from decimal import Decimal as D; print(D('$AF_BEFORE') + D('$CREDITED') - 105)")
for _ in $(seq 1 40); do
  [[ "$(balance $AF1)" == "$EXPECTED" ]] && break; sleep 3
done
[[ "$(balance $AF1)" == "$EXPECTED" ]] && ok "saldo em África: $AF_BEFORE + $CREDITED - 100.00 - 5.00 = $EXPECTED MZN" || fail "saldo $(balance $AF1), esperado $EXPECTED"
sql "$CORE" "SELECT holder_region AS de, target_region AS para, target_iban, amount AS saldo_restante, currency, movements, state FROM custody_forwards ORDER BY created_at DESC LIMIT 1"
api GET "/accounts/$AF1/movements?limit=6"
info "extrato em África (os movimentos feitos em custódia aparecem com o nó onde aconteceram):"
echo "$LAST_BODY" | jq -r '.[] | "    \(.created_at[11:19])  \(.type)  \(.amount) \(.currency)  \(.origin)  saldo \(.balance_after)\(if .via_region then "  (feito em custódia no shard " + .via_region + ")" else "" end)"'
sql "$EU_SHARD" "SELECT target_iban, balance AS valor_retido FROM custody_accounts WHERE target_iban = '$AF1'"
pause

step "6. Linha temporal da transferência original e consistência"
login ana.silva@cliente.test "$CLIENT_PASSWORD"
api GET "/transfers/$TX_IN"
timeline
echo "$LAST_BODY" | jq -e '[.events[].event] | index("REENCAMINHADA_PARA_AF")' >/dev/null && ok "a transferência foi reencaminhada para África" || fail "sem evento de reencaminhamento"
check_consistency

title "Cenário 17 concluído"
