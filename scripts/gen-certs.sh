#!/usr/bin/env bash
# Generates a local Certificate Authority and one TLS certificate per service.
# Each certificate has SANs: <name>, <name>.global.local and the fixed IP on globalnet.
# Output: infra/certs/ (ca.crt, ca.key, <name>.crt, <name>.key, legacy-bank.p12)
set -euo pipefail

cd "$(dirname "$0")/.."
OUT=infra/certs
mkdir -p "$OUT"

# name:ip  (must match docker-compose.yml)
SERVICES=(
  "nginx:172.28.0.10"
  "api-1:172.28.0.11"
  "api-2:172.28.0.12"
  "auth:172.28.0.20"
  "coordinator:172.28.0.30"
  "legacy-bank:172.28.0.40"
  "nfs:172.28.0.50"
  "pg-core:172.28.0.60"
  "pg-europa:172.28.0.61"
  "pg-america:172.28.0.63"
  "pg-africa:172.28.0.65"
)

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

if [[ -f "$OUT/ca.key" && $FORCE == 0 ]]; then
  echo "[gen-certs] CA já existe em $OUT (usa --force para regenerar tudo)."
else
  echo "[gen-certs] A criar a CA local (Global Scale Local CA)..."
  openssl genrsa -out "$OUT/ca.key" 4096 2>/dev/null
  # RFC 5280 CA extensions (strict verifiers, e.g. Python 3.13+, require keyUsage on the CA).
  openssl req -x509 -new -key "$OUT/ca.key" -sha256 -days 825 \
    -subj "/C=MZ/O=Global Scale Corporation/CN=Global Scale Local CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -out "$OUT/ca.crt"
fi

for entry in "${SERVICES[@]}"; do
  name="${entry%%:*}"
  ip="${entry##*:}"
  # Existing certificates are kept (a new node does not invalidate the others);
  # --force regenerates everything, CA included.
  if [[ $FORCE == 0 && -f "$OUT/$name.crt" && -f "$OUT/$name.key" ]]; then
    echo "[gen-certs] $name: certificado existente mantido"
    continue
  fi
  echo "[gen-certs] Certificado para $name ($name.global.local, $ip)"

  openssl genrsa -out "$OUT/$name.key" 2048 2>/dev/null
  openssl req -new -key "$OUT/$name.key" \
    -subj "/C=MZ/O=Global Scale Corporation/CN=$name.global.local" \
    -out "$OUT/$name.csr"

  san="DNS:$name, DNS:$name.global.local, IP:$ip"
  # nginx is also reached from the host (curl https://localhost), so it needs these names too.
  [[ "$name" == "nginx" ]] && san="$san, DNS:localhost, IP:127.0.0.1"
  # Num servidor: NGINX_EXTRA_SANS="IP:203.0.113.10" (ou "DNS:nome,IP:...") para o browser aceitar esse endereço.
  [[ "$name" == "nginx" && -n "${NGINX_EXTRA_SANS:-}" ]] && san="$san, $NGINX_EXTRA_SANS"
  # Both api instances answer as "api.global.local" too: nginx verifies that one name
  # whichever instance (upstream) it picks.
  [[ "$name" == api-* ]] && san="$san, DNS:api.global.local"

  cat > "$OUT/$name.ext" <<EOF
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
subjectAltName = $san
EOF

  openssl x509 -req -in "$OUT/$name.csr" -CA "$OUT/ca.crt" -CAkey "$OUT/ca.key" \
    -CAcreateserial -days 825 -sha256 -extfile "$OUT/$name.ext" \
    -out "$OUT/$name.crt" 2>/dev/null
  rm -f "$OUT/$name.csr" "$OUT/$name.ext"
done

# Java (legacy-bank) reads a PKCS12 keystore; password is not secret in this prototype.
[[ -f "$OUT/legacy-bank.p12" && $FORCE == 0 ]] || openssl pkcs12 -export -name legacy-bank \
  -inkey "$OUT/legacy-bank.key" -in "$OUT/legacy-bank.crt" -certfile "$OUT/ca.crt" \
  -passout pass:changeit -out "$OUT/legacy-bank.p12"

# Containers run as different users; keys must be readable inside them.
# (Postgres copies its key with 0600 in its own entrypoint — Phase 1.)
chmod 644 "$OUT"/*.crt "$OUT"/*.p12
chmod 640 "$OUT"/*.key
chmod 600 "$OUT/ca.key"

echo "[gen-certs] A verificar todos os certificados contra a CA..."
for entry in "${SERVICES[@]}"; do
  openssl verify -CAfile "$OUT/ca.crt" "$OUT/${entry%%:*}.crt"
done
echo "[gen-certs] Concluído."
