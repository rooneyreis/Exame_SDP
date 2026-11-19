#!/usr/bin/env bash
# Scenario 07: auth goes down -> tokens already issued keep working on the api
# (decentralised validation with the cached public key) -> new logins fail -> auth back.
source "$(dirname "$0")/lib.sh"

title "Cenário 07 — Queda do serviço de autenticação"

step "1. Login normal e pedido à API"
login david.smith@cliente.test "$CLIENT_PASSWORD"
SAVED_TOKEN=$TOKEN
api GET /accounts
expect 200 "conta lida"; show '[.[] | {iban, balance}]'
info "kid do token: $(echo "$TOKEN" | cut -d. -f1 | base64 -d 2>/dev/null | jq -r .kid)"
pause

step "2. Derrubar o auth"
cmd "docker stop auth"; docker stop auth >/dev/null
ok "auth parado (a chave privada está inacessível: não se emitem tokens novos)"

step "3. O token existente continua a ser aceite pelas duas instâncias da API"
TOKEN=$SAVED_TOKEN
for _ in 1 2 3 4; do
  api GET /accounts
  [[ "$LAST_STATUS" == 200 ]] || fail "token devia continuar válido"
done
ok "validado localmente com a chave pública em cache (JWKS), sem contactar o auth"
api GET /health
info "jwks em cache na $LAST_SERVED: $(echo "$LAST_BODY" | jq -c .components.jwks.kids)"
pause

step "4. Um login novo falha (o emissor de tokens está em baixo)"
TOKEN=""
api POST /auth/login "{\"email\":\"emily.johnson@cliente.test\",\"password\":\"$CLIENT_PASSWORD\"}"
[[ "$LAST_STATUS" =~ ^5 ]] && ok "login recusado com HTTP $LAST_STATUS (auth indisponível)" || fail "esperava 5xx"

step "5. Um token forjado continua a ser rejeitado (a api não aceita qualquer coisa só porque o auth caiu)"
FORGED="$(echo "$SAVED_TOKEN" | cut -d. -f1).$(echo -n '{"sub":"x","role":"admin"}' | base64 | tr '+/' '-_' | tr -d '=').$(echo "$SAVED_TOKEN" | cut -d. -f3)"
TOKEN=$FORGED
api GET /accounts
expect 401 "token adulterado rejeitado"
pause

step "6. Voltar a ligar o auth"
cmd "docker start auth"; docker start auth >/dev/null
wait_healthy auth
login emily.johnson@cliente.test "$CLIENT_PASSWORD"
ok "login volta a funcionar"

title "Cenário 07 concluído"
