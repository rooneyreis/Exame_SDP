#!/usr/bin/env bash
# Scenario 14: the third region, África (AF, MZN), in a shard of its own (pg-africa, with its
# copy on pg-europa).
# Registration and KYC open a GS-AF account in MZN; local and 2PC transfers with EU and AM;
# the África shard voting NO aborts the transfer; automatic takeover by the copy and return.
source "$(dirname "$0")/lib.sh"

title "Cenário 14 — Região África (AF, MZN)"

step "1. Três regiões, três shards: cada um no seu nó, com a cópia no nó seguinte do anel"
topology
[[ "$(db_role pg-africa 5432)" == f ]] && ok "pg-africa é o primário de África" || fail "pg-africa não é o primário"
[[ "$(db_role pg-europa 5433)" == t ]] && ok "a cópia de África está em pg-europa:5433, a receber em streaming" || fail "a cópia de África não está a seguir"
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
sql "host=pg-africa.global.local,pg-europa.global.local port=5432,5433 target_session_attrs=read-write dbname=bank" \
    "SELECT iban, currency, balance, inet_server_addr() AS no FROM accounts WHERE iban = '$NEW_IBAN'"
sql "host=pg-europa.global.local,pg-america.global.local port=5432,5433 target_session_attrs=read-write dbname=bank" \
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

step "7. O nó pg-africa cai: a cópia em pg-europa assume o papel de África sozinha"
cmd "docker stop pg-africa"; docker stop pg-africa >/dev/null
SECS=$(wait_role pg-europa 5433 f 40) || fail "a cópia de África não assumiu o papel"
ok "pg-europa:5433 é agora o primário de África (assumiu em ${SECS}s, sem nenhum comando)"
login amina.mussa@cliente.test "$CLIENT_PASSWORD"
transfer GS-AF-00000001 GS-AF-00000003 200.00 "demo14-failover-$N"
expect 201 "transferência AF → AF servida pela cópia, sem mudar configuração"
pause

step "8. pg-africa volta: sincroniza-se a partir da cópia e retoma o seu papel"
cmd "docker start pg-africa"; docker start pg-africa >/dev/null
wait_all_home || fail "a topologia não voltou ao normal"
topology
ok "pg-africa é de novo o primário de África e pg-europa:5433 voltou a ser a sua cópia"
pause

step "9. Verificação final nos três shards"
check_consistency

title "Cenário 14 concluído"
