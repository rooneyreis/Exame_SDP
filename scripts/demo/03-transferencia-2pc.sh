#!/usr/bin/env bash
# Scenario 03: EU (EUR) -> AM (USD) transfer with exchange. The accounts are in different
# shards: Two-Phase Commit coordinated by the coordinator, kind=DISTRIBUIDA.
source "$(dirname "$0")/lib.sh"

title "Cenário 03 — Transferência distribuída com 2PC (EU/EUR → AM/USD)"
FROM=GS-EU-00000001; TO=GS-AM-00000001
B_FROM=$(balance $FROM); B_TO=$(balance $TO)
info "saldos antes: $FROM=$B_FROM EUR (pg-europa)   $TO=$B_TO USD (pg-america)"

step "1. Ana (EU) transfere 100.00 EUR para o David (AM)"
login ana.silva@cliente.test "$CLIENT_PASSWORD"
transfer $FROM $TO 100.00 "demo03-$(date +%s%N)"
expect 201 "transferência confirmada"
show '{tx_id, kind, state, amount, from_currency, fx_rate, converted_amount, to_currency}'
TX=$(echo "$LAST_BODY" | jq -r .tx_id)
pause

step "2. Linha temporal do 2PC (tabela tx_events no log do coordenador)"
timeline
info ""
info "Fase 1: cada shard faz BEGIN … UPDATE … PREPARE TRANSACTION e vota SIM (PREPARADO_*)"
info "Ponto de decisão: DECISAO_COMMIT gravada (commit) no pg-core ANTES de qualquer COMMIT PREPARED"
info "Fase 2: COMMIT PREPARED em cada shard → CONFIRMADA"
pause

step "3. Os movimentos, vistos diretamente em cada Postgres"
info "pg-europa (débito em EUR):"
sql "host=pg-europa.global.local,pg-europa-replica.global.local target_session_attrs=read-write dbname=bank" \
  "SELECT iban, type, amount, currency, balance_after FROM movements WHERE tx_id = '$TX'"
info "pg-america (crédito em USD, já convertido):"
sql "host=pg-america.global.local,pg-america-replica.global.local target_session_attrs=read-write dbname=bank" \
  "SELECT iban, type, amount, currency, balance_after FROM movements WHERE tx_id = '$TX'"
info "nenhuma transação ficou preparada (pendurada):"
prepared_xacts

step "4. Saldos depois"
A_FROM=$(balance $FROM); A_TO=$(balance $TO)
info "$FROM: $B_FROM → $A_FROM EUR    $TO: $B_TO → $A_TO USD"
decimal_true "D('$B_FROM') - 100 == D('$A_FROM') and D('$B_TO') + 108 == D('$A_TO')" && ok "−100.00 EUR / +108.00 USD (taxa 1.08)" || fail "saldos errados"
check_consistency

title "Cenário 03 concluído"
