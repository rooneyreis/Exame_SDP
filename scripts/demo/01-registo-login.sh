#!/usr/bin/env bash
# Scenario 01: registration (EU and AM) -> pending -> operator approves KYC ->
# account created IN THE RIGHT SHARD (checked directly in each Postgres) -> login -> JWT.
source "$(dirname "$0")/lib.sh"

title "Cenário 01 — Registo, KYC, conta no shard certo e login"
N=$(date +%s)

step "1. Registo de um cliente da Europa e de um cliente da América"
TOKEN=""
api POST /auth/register "{\"full_name\":\"Maria Europa\",\"email\":\"maria.$N@demo.test\",\"phone\":\"+3519${N: -8}\",\"password\":\"Demo#2026\",\"region\":\"EU\",\"document_id\":\"PT$N\",\"birth_date\":\"1992-05-10\"}"
expect 201 "cliente EU registado"; show
EU_ID=$(echo "$LAST_BODY" | jq -r .id)
api POST /auth/register "{\"full_name\":\"John America\",\"email\":\"john.$N@demo.test\",\"phone\":\"+1202${N: -7}\",\"password\":\"Demo#2026\",\"region\":\"AM\",\"document_id\":\"US$N\",\"birth_date\":\"1987-02-03\"}"
expect 201 "cliente AM registado"; show
AM_ID=$(echo "$LAST_BODY" | jq -r .id)
pause

step "2. Ainda pendente: o login é recusado"
api POST /auth/login "{\"email\":\"maria.$N@demo.test\",\"password\":\"Demo#2026\"}"
expect 403 "login recusado enquanto PENDENTE_VERIFICACAO"; show .detail

step "3. Na BD, o documento de identificação está cifrado (AES-256-GCM)"
sql "host=pg-core.global.local,pg-america.global.local port=5432,5434 target_session_attrs=read-write dbname=auth" "SELECT email, status, encode(substr(document_id_enc,1,24),'hex') AS document_id_enc FROM users WHERE id = '$EU_ID'"
pause

step "4. O operador aprova o KYC dos dois clientes"
login operador@globalscale.test "$STAFF_PASSWORD"
api GET "/admin/users?status=PENDENTE_VERIFICACAO"
info "pendentes: $(echo "$LAST_BODY" | jq -r '[.[].email] | join(", ")')"
api POST "/admin/users/$EU_ID/approve-kyc"
expect 200 "KYC EU aprovado"; show .account
EU_IBAN=$(echo "$LAST_BODY" | jq -r .account.iban)
api POST "/admin/users/$AM_ID/approve-kyc"
expect 200 "KYC AM aprovado"; show .account
AM_IBAN=$(echo "$LAST_BODY" | jq -r .account.iban)
pause

step "5. Consulta direta a cada shard: cada conta só existe no nó da sua região"
EU_SHARD="host=pg-europa.global.local,pg-america.global.local port=5432,5433 target_session_attrs=read-write dbname=bank"
AM_SHARD="host=pg-america.global.local,pg-africa.global.local port=5432,5433 target_session_attrs=read-write dbname=bank"
info "pg-europa:"
sql "$EU_SHARD" "SELECT iban, currency, balance FROM accounts WHERE user_id IN ('$EU_ID','$AM_ID')"
info "pg-america:"
sql "$AM_SHARD" "SELECT iban, currency, balance FROM accounts WHERE user_id IN ('$EU_ID','$AM_ID')"
in_eu=$(docker compose run --rm -T pgclient "$EU_SHARD sslmode=verify-full" -tAc "SELECT count(*) FROM accounts WHERE iban IN ('$EU_IBAN','$AM_IBAN')" 2>/dev/null) 
in_am=$(docker compose run --rm -T pgclient "$AM_SHARD sslmode=verify-full" -tAc "SELECT count(*) FROM accounts WHERE iban IN ('$EU_IBAN','$AM_IBAN')" 2>/dev/null) 
[[ "$EU_IBAN" == GS-EU-* && "$AM_IBAN" == GS-AM-* && "$in_eu" == 1 && "$in_am" == 1 ]] \
  && ok "$EU_IBAN só no pg-europa, $AM_IBAN só no pg-america" || fail "fragmentação incorreta"
info "a cópia da Europa, guardada no nó pg-america (porta 5433), também a tem (replicação síncrona):"
sql "host=pg-america.global.local port=5433 dbname=bank" "SELECT iban, pg_is_in_recovery() AS copia FROM accounts WHERE iban = '$EU_IBAN'"
pause

step "6. Login do cliente EU: JWT RS256 emitido pelo auth"
login "maria.$N@demo.test" "Demo#2026"
ok "token recebido"
info "header: $(echo "$TOKEN" | cut -d. -f1 | base64 -d 2>/dev/null)"
info "claims:"; jwt_claims "$TOKEN"

step "7. GET /me — validado localmente pela api com a chave pública (JWKS)"
api GET /me
expect 200 "dados do token e contas"; show '{user_id, role, region, accounts: [.accounts[] | {iban, currency, balance}]}'

title "Cenário 01 concluído"
