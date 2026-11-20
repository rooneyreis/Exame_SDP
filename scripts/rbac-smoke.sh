#!/usr/bin/env bash
# Matriz de acesso real: chama a API diretamente (como faria um atacante, sem passar pela interface)
# com cada perfil e mostra o código HTTP de cada endpoint protegido.
set -euo pipefail
cd "$(dirname "$0")/.."
C=(--cacert infra/certs/ca.crt -s -o /dev/null -w '%{http_code}')
tok() { curl --cacert infra/certs/ca.crt -s https://localhost/auth/login -H 'content-type: application/json' \
          -d "{\"email\":\"$1\",\"password\":\"$2\"}" | jq -r .access_token; }
declare -A T=(
  [cliente]=$(tok ana.silva@cliente.test 'Cliente#2026')
  [operador]=$(tok operador@globalscale.test 'Staff#2026')
  [auditor]=$(tok auditor@globalscale.test 'Staff#2026')
  [admin]=$(tok admin@globalscale.test 'Staff#2026')
)
ENDPOINTS=(
  "GET /admin/users"
  "GET /admin/roles"
  "PATCH /admin/users/00000000-0000-4000-8000-000000000003"
  "GET /admin/transfers"
  "GET /admin/accounts"
  "PATCH /admin/accounts/GS-EU-00000003"
  "GET /admin/settings"
  "PUT /admin/settings"
  "GET /admin/overview"
  "GET /admin/suspicious"
  "GET /admin/audit/events"
  "GET /admin/status"
  "GET /transfer-requests"
  "POST /transfer-requests"
  "POST /transfer-requests/00000000-0000-0000-0000-000000000000/approve"
  "POST /accounts/GS-EU-00000003/deposit"
  "GET /admin/beneficiaries"
  "GET /beneficiaries"
)
printf '%-62s %9s %9s %9s %9s\n' "endpoint" cliente operador auditor admin
for ep in "${ENDPOINTS[@]}"; do
  method=${ep%% *}; path=${ep#* }
  row=$(printf '%-62s' "$ep")
  for r in cliente operador auditor admin; do
    # corpo vazio/inválido de propósito: interessa só se passa a barreira de permissões (403 = bloqueado)
    code=$(curl "${C[@]}" -X "$method" "https://localhost$path" -H "Authorization: Bearer ${T[$r]}" \
           -H 'content-type: application/json' -d '{}')
    row+=$(printf ' %9s' "$code")
  done
  echo "$row"
done
echo
echo "403 = recusado pelo RBAC no backend · 401 = sem sessão · 404/409/422 = passou a permissão (pedido incompleto de propósito)"
