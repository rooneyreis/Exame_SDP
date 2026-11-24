#!/usr/bin/env bash
# Scenario 08: the node pg-europa goes down. Its copy, kept on pg-america, takes over the
# role of the Europa database BY ITSELF within seconds: transfers keep working without any
# command and without changing configuration. When pg-europa comes back it re-syncs from
# the copy and takes its role back, also by itself.
source "$(dirname "$0")/lib.sh"

title "Cenário 08 — Um nó cai e a cópia noutro nó assume o seu papel"

step "1. Situação inicial: cada base no seu nó, com a cópia no nó seguinte do anel"
topology
login ana.silva@cliente.test "$CLIENT_PASSWORD"
transfer GS-EU-00000001 GS-EU-00000002 1.00 "demo08a-$(date +%s%N)"
expect 201 "transferência EU → EU no pg-europa"
B_BEFORE=$(balance GS-EU-00000001)
pause

step "2. Derrubar o nó pg-europa (sem mais nenhum comando)"
cmd "docker stop pg-europa"; docker stop pg-europa >/dev/null
ok "pg-europa parado: a base da Europa (e a cópia de África que ele guardava) ficaram em baixo"
info "o supervisor do pg-america vê que o dono desapareceu e promove a cópia..."
SECS=$(wait_role pg-america 5433 f 40) || fail "a cópia não assumiu o papel"
ok "a cópia da Europa em pg-america:5433 é agora o PRIMÁRIO (assumiu em ${SECS}s)"
docker logs pg-america 2>&1 | grep -E "supervisor pg-america/EU" | grep -E "PROMOÇÃO|síncrona|assíncrona" | tail -2 | sed 's/^/    /'
topology
pause

step "3. A Europa continua a aceitar operações, sem mudar configuração nenhuma"
info "(os serviços ligam-se com host=pg-europa,pg-america port=5432,5433 target_session_attrs=read-write)"
transfer GS-EU-00000001 GS-EU-00000002 1.00 "demo08b-$(date +%s%N)"
expect 201 "LOCAL EU → EU servida pela cópia"
TX_DURING=$(echo "$LAST_BODY" | jq -r .tx_id)
transfer GS-EU-00000001 GS-AM-00000002 1.00 "demo08c-$(date +%s%N)"
expect 201 "DISTRIBUIDA EU → AM (2PC) com a Europa servida pela cópia"
with_user operador@globalscale.test "$STAFF_PASSWORD" POST /accounts/GS-EU-00000003/deposit '{"amount":"5.00"}'
expect 200 "depósito numa conta da Europa"
with_user operador@globalscale.test "$STAFF_PASSWORD" POST /accounts/GS-EU-00000003/withdraw '{"amount":"5.00"}'
expect 200 "levantamento numa conta da Europa"
api GET /health
info "a api escreve agora em: $(echo "$LAST_BODY" | jq -r .components.shard_EU.node) (pg-america = 172.28.0.63)"
pause

step "4. pg-europa volta: sincroniza-se a partir da cópia e retoma o seu papel sozinho"
cmd "docker start pg-europa"; docker start pg-europa >/dev/null
wait_all_home || fail "a topologia não voltou ao normal"
docker logs pg-europa 2>&1 | grep -E "supervisor pg-europa/EU" | grep -E "primário mais recente|PROMOÇÃO|a copiar" | tail -3 | sed 's/^/    /'
docker logs pg-america 2>&1 | grep -E "supervisor pg-america/EU" | grep RETOMA | tail -1 | sed 's/^/    /'
topology
ok "pg-europa é de novo o primário da Europa e pg-america:5433 voltou a ser a sua cópia"
info "a transferência feita durante a falha está no pg-europa:"
sql "host=pg-europa.global.local port=5432 dbname=bank" "SELECT iban, type, amount FROM movements WHERE tx_id = '$TX_DURING' ORDER BY type"
decimal_true "D('$B_BEFORE') - 2 == D('$(balance GS-EU-00000001)')" && ok "saldo de GS-EU-00000001: −2.00 EUR (as duas transferências feitas na falha), sem perdas nem duplicados" || fail "saldo errado"
check_consistency

title "Cenário 08 concluído"
