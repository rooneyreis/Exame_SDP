#!/usr/bin/env bash
# Scenario 14: the third region, África (AF, MZN), in a shard of its own (pg-africa + replica).
# Registration and KYC open a GS-AF account in MZN; local and 2PC transfers with EU and AM;
# the África shard voting NO aborts the transfer; failover of the África shard and failback.
source "$(dirname "$0")/lib.sh"

title "Cenário 14 — Região África (AF, MZN)"

step "1. Três regiões, três shards: cada um com primário e réplica"
with_user admin@globalscale.test "$STAFF_PASSWORD" GET /admin/status
echo "$LAST_BODY" | jq -r '.databases | to_entries[] | "    \(.key | .+ "                    " | .[0:20]) \(if .value.up then .value.role else "EM BAIXO" end)  ssl=\(.value.ssl // "-")"'
[[ "$(echo "$LAST_BODY" | jq -r '.databases["pg-africa"].role')" == "primário" ]] && ok "pg-africa é primário" || fail "pg-africa não está como primário"
[[ "$(echo "$LAST_BODY" | jq -r '.databases["pg-africa-replica"].role')" == "réplica" ]] && ok "pg-africa-replica é réplica em streaming" || fail "pg-africa-replica não está como réplica"
pause

step "2. Registo de uma cliente em África → KYC → conta GS-AF em MZN no shard África"
N=$(date +%s%N | tail -c 8)
TOKEN=""
api POST /auth/register "{\"full_name\":\"Fátima Nhantumbo\",\"email\":\"fatima.$N@demo.test\",\"phone\":\"+25882$N\",\"password\":\"Demo#2026\",\"region\":\"AF\",\"document_id\":\"MZ$N\",\"birth_date\":\"1994-05-20\"}"
expect 201 "registo com região AF"
USER_ID=$(echo "$LAST_BODY" | jq -r .id)
with_user operador@globalscale.test "$STAFF_PASSWORD" POST "/admin/users/$USER_ID/approve-kyc"
expect 200 "KYC aprovado pelo operador"
show '.account | {iban, currency, region}'
NEW_IBAN=$(echo "$LAST_BODY" | jq -r .account.iban)
[[ "$NEW_IBAN" == GS-AF-* && "$(echo "$LAST_BODY" | jq -r .account.currency)" == MZN ]] && ok "conta $NEW_IBAN aberta em MZN" || fail "conta errada"
sql "host=pg-africa.global.local,pg-africa-replica.global.local target_session_attrs=read-write dbname=bank" \
    "SELECT iban, currency, balance, inet_server_addr() AS no FROM accounts WHERE iban = '$NEW_IBAN'"
sql "host=pg-europa.global.local,pg-europa-replica.global.local target_session_attrs=read-write dbname=bank" \
    "SELECT count(*) AS contas_af_na_europa FROM accounts WHERE iban LIKE 'GS-AF-%'"
pause

step "3. Transferência local AF → AF (uma só transação, sem 2PC)"
login amina.mussa@cliente.test "$CLIENT_PASSWORD"
transfer GS-AF-00000001 GS-AF-00000002 1500.00 "demo14-local-$N"
expect 201 "AF → AF"
show '{state, kind, amount, from_currency, to_currency}'
timeline
[[ "$(echo "$LAST_BODY" | jq -r .kind)" == LOCAL ]] && ok "kind=LOCAL" || fail "esperava LOCAL"
pause

step "4. 2PC Europa → África: 100.00 EUR → MZN"
login ana.silva@cliente.test "$CLIENT_PASSWORD"
B_TO=$(balance GS-AF-00000002)
transfer GS-EU-00000001 GS-AF-00000002 100.00 "demo14-eu-af-$N"
expect 201 "EU → AF"
show '{state, kind, amount, from_currency, fx_rate, converted_amount, to_currency}'
timeline
A_TO=$(balance GS-AF-00000002)
decimal_true "D('$B_TO') + D('7050.00') == D('$A_TO')" && ok "GS-AF-00000002: $B_TO → $A_TO MZN (+7050.00 à taxa 70.5)" || fail "saldo de destino errado"
pause

step "5. 2PC África → América: a ordem global de bloqueio é EU → AM → AF"
login amina.mussa@cliente.test "$CLIENT_PASSWORD"
transfer GS-AF-00000001 GS-AM-00000002 6390.00 "demo14-af-am-$N"
expect 201 "AF → AM"
show '{state, kind, amount, from_currency, fx_rate, converted_amount, to_currency}'
timeline
[[ "$(echo "$LAST_BODY" | jq -r '[.events[].event] | index("PREPARADO_AM") < index("PREPARADO_AF")')" == true ]] \
  && ok "AM preparado antes de AF, apesar de o débito ser em África: sem deadlocks distribuídos" || fail "ordem de PREPARE errada"
pause

step "6. O shard África vota NÃO → a Europa, já preparada, é desfeita"
chaos '{"fail_participant": "AF"}'
login ana.silva@cliente.test "$CLIENT_PASSWORD"
B_FROM=$(balance GS-EU-00000001)
transfer GS-EU-00000001 GS-AF-00000003 25.00 "demo14-abort-$N"
expect 422 "transferência abortada"
show '{state, failure_reason}'
timeline
chaos '{"off": true}'
A_FROM=$(balance GS-EU-00000001)
[[ "$B_FROM" == "$A_FROM" ]] && ok "saldo da Ana intacto: $A_FROM EUR" || fail "a Europa foi debitada"
prepared_xacts
pause

step "7. Failover do shard África"
cmd "docker stop pg-africa"; docker stop pg-africa >/dev/null
ok "primário de África parado"
cmd "./scripts/failover.sh AF"; ./scripts/failover.sh AF | sed 's/^/    /'
login amina.mussa@cliente.test "$CLIENT_PASSWORD"
transfer GS-AF-00000001 GS-AF-00000003 200.00 "demo14-failover-$N"
expect 201 "transferência AF → AF servida pelo novo primário (pg-africa-replica), sem mudar configuração"
cmd "docker start pg-africa"; docker start pg-africa >/dev/null
for _ in $(seq 1 60); do
  [[ "$(docker exec pg-africa psql -U postgres -tAc 'SELECT pg_is_in_recovery()' 2>/dev/null)" == t ]] && break; sleep 2
done
[[ "$(docker exec pg-africa psql -U postgres -tAc 'SELECT pg_is_in_recovery()')" == t ]] && ok "pg-africa voltou sozinho como RÉPLICA (sem split-brain)" || fail "pg-africa não voltou como réplica"
pause

step "8. Failback: repor a topologia original"
cmd "docker stop pg-africa-replica && ./scripts/failover.sh AF && docker start pg-africa-replica"
docker stop pg-africa-replica >/dev/null
./scripts/failover.sh AF | grep -E 'OK|ERRO' | sed 's/^/    /'
docker start pg-africa-replica >/dev/null
for _ in $(seq 1 60); do
  [[ "$(docker exec pg-africa psql -U postgres -tAc "SELECT count(*) FROM pg_stat_replication WHERE state='streaming'" 2>/dev/null)" == 1 ]] && break; sleep 2
done
[[ "$(docker exec pg-africa psql -U postgres -tAc 'SELECT pg_is_in_recovery()')" == f ]] && ok "pg-africa é de novo o primário e pg-africa-replica a réplica" || fail "failback falhou"
wait_healthy pg-africa-replica
pause

step "9. Verificação final nos três shards"
check_consistency

title "Cenário 14 concluído"
