#!/usr/bin/env bash
# Scenario 04: the same request sent 3 times with the same Idempotency-Key -> executed once.
source "$(dirname "$0")/lib.sh"

title "Cenário 04 — Idempotência"
FROM=GS-AM-00000002; TO=GS-EU-00000003
KEY="demo04-$(date +%s%N)"
B_FROM=$(balance $FROM)

step "1. A Emily envia a mesma transferência 3 vezes (ex.: o cliente repetiu por timeout de rede)"
login emily.johnson@cliente.test "$CLIENT_PASSWORD"
info "Idempotency-Key: $KEY"
IDS=()
for i in 1 2 3; do
  transfer $FROM $TO 25.00 "$KEY"
  info "envio $i: HTTP $LAST_STATUS  tx_id=$(echo "$LAST_BODY" | jq -r .tx_id)  state=$(echo "$LAST_BODY" | jq -r .state)  replay=$(echo "$LAST_BODY" | jq -r .idempotent_replay)"
  IDS+=("$(echo "$LAST_BODY" | jq -r .tx_id)")
done
[[ "${IDS[0]}" == "${IDS[1]}" && "${IDS[1]}" == "${IDS[2]}" ]] && ok "o mesmo tx_id nas 3 respostas" || fail "tx_ids diferentes"
pause

step "2. Só existe UM débito no shard"
sql "host=pg-america.global.local,pg-america-replica.global.local target_session_attrs=read-write dbname=bank" \
  "SELECT count(*) AS debitos FROM movements WHERE tx_id = '${IDS[0]}' AND type = 'DEBITO'"
A_FROM=$(balance $FROM)
info "saldo $FROM: $B_FROM → $A_FROM USD"
decimal_true "D('$B_FROM') - 25 == D('$A_FROM')" && ok "debitado uma única vez (−25.00)" || fail "débito duplicado!"
info "os pedidos repetidos ficam registados no log:"
api GET "/transfers/${IDS[0]}"; timeline

step "3. Reutilizar a chave com outro montante é recusado"
transfer $FROM $TO 999.00 "$KEY"
expect 409 "Idempotency-Key já usada com outros dados"

title "Cenário 04 concluído"
