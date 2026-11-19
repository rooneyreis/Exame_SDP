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
  "pg-europa-replica:172.28.0.62"
  "pg-america:172.28.0.63"
  "pg-america-replica:172.28.0.64"
)

if [[ -f "$OUT/ca.key" && "${1:-}" != "--force" ]]; then
  echo "[gen-certs] CA já existe em $OUT (usa --force para regenerar tudo)."
else
  echo "[gen-certs] A criar a CA local (Global Scale Local CA)..."
  openssl genrsa -out "$OUT/ca.key" 4096 2>/dev/null
  openssl req -x509 -new -key "$OUT/ca.key" -sha256 -days 825 \
    -subj "/C=MZ/O=Global Scale Corporation/CN=Global Scale Local CA" \
    -out "$OUT/ca.crt"
fi

for entry in "${SERVICES[@]}"; do
  name="${entry%%:*}"
  ip="${entry##*:}"
  echo "[gen-certs] Certificado para $name ($name.global.local, $ip)"

  openssl genrsa -out "$OUT/$name.key" 2048 2>/dev/null
  openssl req -new -key "$OUT/$name.key" \
    -subj "/C=MZ/O=Global Scale Corporation/CN=$name.global.local" \
    -out "$OUT/$name.csr"

  cat > "$OUT/$name.ext" <<EOF
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = DNS:$name, DNS:$name.global.local, IP:$ip
EOF

  openssl x509 -req -in "$OUT/$name.csr" -CA "$OUT/ca.crt" -CAkey "$OUT/ca.key" \
    -CAcreateserial -days 825 -sha256 -extfile "$OUT/$name.ext" \
    -out "$OUT/$name.crt" 2>/dev/null
  rm -f "$OUT/$name.csr" "$OUT/$name.ext"
done

# Java (legacy-bank) reads a PKCS12 keystore; password is not secret in this prototype.
openssl pkcs12 -export -name legacy-bank \
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
