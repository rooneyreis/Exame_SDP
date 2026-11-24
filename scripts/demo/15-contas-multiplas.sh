#!/usr/bin/env bash
# Scenario 15: several accounts per client, in different regions and currencies.
# A client registered in Europe asks for an account in África (MZN) -> an operator approves ->
# the account exists ONLY in pg-africa -> transfer between the client's own accounts EU -> AF
# (2PC + exchange) -> the daily limit per client (in EUR, all accounts summed) is updated.
source "$(dirname "$0")/lib.sh"

title "Cenário 15 — Várias contas por cliente (regiões e moedas diferentes)"

step "1. Um cliente novo, registado na Europa, com a primeira conta aberta pelo KYC"
N=$(date +%s%N | tail -c 8)
EMAIL="sofia.$N@demo.test"
TOKEN=""
api POST /auth/register "{\"full_name\":\"Sofia Tembe\",\"email\":\"$EMAIL\",\"phone\":\"+35191$N\",\"password\":\"Demo#2026\",\"region\":\"EU\",\"document_id\":\"PT$N\",\"birth_date\":\"1991-07-14\"}"
expect 201 "registo na região EU"
USER_ID=$(echo "$LAST_BODY" | jq -r .id)
with_user operador@globalscale.test "$STAFF_PASSWORD" POST "/admin/users/$USER_ID/approve-kyc"
expect 200 "KYC aprovado"
EU_IBAN=$(echo "$LAST_BODY" | jq -r .account.iban)
with_user operador@globalscale.test "$STAFF_PASSWORD" POST "/accounts/$EU_IBAN/deposit" '{"amount":"2000.00"}'
expect 200 "depósito de 2000.00 EUR ao balcão em $EU_IBAN"
login "$EMAIL" "Demo#2026"
api GET /accounts
show '[.[] | {iban, region, currency, balance}]'
pause

step "2. O cliente pede uma conta em África, em meticais"
api POST /account-requests '{"region":"AF","currency":"MZN"}'
expect 201 "pedido registado"
show '{id, kind, region, currency, status}'
REQ=$(echo "$LAST_BODY" | jq -r .id)
api POST /account-requests '{"region":"AF","currency":"MZN"}'
expect 409 "um segundo pedido igual é recusado"
pause

step "3. O operador vê o pedido na fila e aprova"
with_user operador@globalscale.test "$STAFF_PASSWORD" GET "/admin/account-requests?status=PENDENTE"
echo "$LAST_BODY" | jq -c --arg id "$REQ" '.[] | select(.id == $id) | {id, user_id, kind, region, currency, status}' | sed 's/^/    /'
with_user operador@globalscale.test "$STAFF_PASSWORD" POST "/admin/account-requests/$REQ/approve"
expect 200 "pedido aprovado"
show '{request: .request.status, account: (.account | {iban, region, currency, created})}'
AF_IBAN=$(echo "$LAST_BODY" | jq -r .account.iban)
with_user operador@globalscale.test "$STAFF_PASSWORD" POST "/admin/account-requests/$REQ/approve"
expect 409 "aprovar outra vez não cria uma segunda conta"
pause

step "4. A conta existe só no shard África (o cliente registou-se na Europa)"
for node in pg-europa pg-america pg-africa; do
  sql "host=$node.global.local port=5432 dbname=bank" \
      "SELECT '$node' AS no, count(*) AS contas_do_cliente, string_agg(iban || ' ' || currency, ', ') AS contas FROM accounts WHERE user_id = '$USER_ID'"
done
login "$EMAIL" "Demo#2026"
api GET /accounts
show '[.[] | {iban, region, currency, balance, status}]'
[[ "$(echo "$LAST_BODY" | jq length)" == 2 ]] && ok "GET /accounts junta as contas dos dois shards" || fail "esperava 2 contas"
pause

step "5. Limites antes"
api GET /me/limits
show '{daily_limit_eur, sent_today_eur, remaining_eur, max_transfer_eur, active_accounts, max_accounts}'
pause

step "6. Transferência entre as contas do próprio cliente: EU (EUR) → AF (MZN), 2PC com câmbio"
transfer "$EU_IBAN" "$AF_IBAN" 100.00 "demo15-own-$N"
expect 201 "transferência confirmada"
show '{state, kind, own_transfer, amount, from_currency, fx_rate, converted_amount, to_currency}'
timeline
api GET /me/limits
show '{sent_today_eur, remaining_eur}'
[[ "$(echo "$LAST_BODY" | jq -r .sent_today_eur)" == "0.00" ]] && ok "entre contas próprias não conta para o limite diário (o dinheiro não sai do cliente)" || fail "a transferência própria contou para o limite"
pause

step "7. Um envio para outra pessoa a partir da conta em África: conta para o limite (em EUR)"
transfer "$AF_IBAN" GS-AF-00000001 3525.00 "demo15-out-$N"
expect 201 "3525.00 MZN enviados"
show '{state, amount, from_currency, amount_eur}'
api GET /me/limits
show '{daily_limit_eur, sent_today_eur, remaining_eur, remaining_by_currency}'
[[ "$(echo "$LAST_BODY" | jq -r .sent_today_eur)" == "50.00" ]] && ok "limite atualizado: 3525.00 MZN = 50.00 EUR somados ao dia do cliente" || fail "limite não atualizado"
api GET /accounts
show '[.[] | {iban, currency, balance}]'
pause

step "8. Verificação final"
check_consistency

title "Cenário 15 concluído"
