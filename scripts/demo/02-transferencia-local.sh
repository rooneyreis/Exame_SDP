#!/usr/bin/env bash
# Scenario 02: EU -> EU transfer. Both accounts are in the same shard: a normal local
# ACID transaction (BEGIN ... COMMIT), kind=LOCAL, no 2PC needed.
source "$(dirname "$0")/lib.sh"

title "Cenário 02 — Transferência local (EU → EU)"
FROM=GS-EU-00000001; TO=GS-EU-00000002
B_FROM=$(balance $FROM); B_TO=$(balance $TO)
info "saldos antes: $FROM=$B_FROM EUR   $TO=$B_TO EUR"

step "1. Ana transfere 50.00 EUR para o Bruno (mesmo shard: pg-europa)"
login ana.silva@cliente.test "$CLIENT_PASSWORD"
transfer $FROM $TO 50.00 "demo02-$(date +%s%N)"
expect 201 "transferência confirmada"
show '{tx_id, kind, state, amount, from_currency, to_currency, converted_amount}'
[[ "$(echo "$LAST_BODY" | jq -r .kind)" == LOCAL ]] && ok "kind=LOCAL: uma única transação no pg-europa" || fail "esperava LOCAL"
info "linha temporal (sem PREPARE: não há 2PC):"; timeline
pause

step "2. Saldos depois"
A_FROM=$(balance $FROM); A_TO=$(balance $TO)
info "$FROM: $B_FROM → $A_FROM    $TO: $B_TO → $A_TO"
decimal_true "D('$B_FROM') - 50 == D('$A_FROM') and D('$B_TO') + 50 == D('$A_TO')" && ok "débito e crédito aplicados atomicamente" || fail "saldos errados"

title "Cenário 02 concluído"
