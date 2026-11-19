#!/usr/bin/env bash
# Scenario 11: 50 concurrent transfers between the same accounts (local and distributed,
# in both directions). No negative balances, no hanging locks, money conserved.
source "$(dirname "$0")/lib.sh"

title "Cenário 11 — 50 transferências concorrentes"
step "1. A lançar 50 transferências em paralelo (asyncio + httpx)"
info "Ana GS-EU-00000001 ⇄ Bruno GS-EU-00000002 (LOCAL) e Ana GS-EU-00000001 ⇄ David GS-AM-00000001 (DISTRIBUIDA)"
.venv/bin/python scripts/demo/concurrency.py 50 || fail "verificação falhou"
pause

step "2. Verificação global"
prepared_xacts
check_consistency

title "Cenário 11 concluído"
