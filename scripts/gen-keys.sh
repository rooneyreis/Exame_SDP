#!/usr/bin/env bash
# Generates application keys (separate from TLS certificates):
#   - RS256 key pair for auth (JWT signing). Only auth gets the private key.
#   - Ed25519 key pairs for api-1, api-2, coordinator and legacy-bank (message signatures).
#   - AES-256 data key for auth (encryption at rest of sensitive user fields).
# Output: infra/keys/private/  (mounted only in the owning container)
#         infra/keys/public/   (mounted read-only where verification is needed)
set -euo pipefail

cd "$(dirname "$0")/.."
OUT=infra/keys
mkdir -p "$OUT/private" "$OUT/public"

if [[ -f "$OUT/private/auth-rs256.pem" && "${1:-}" != "--force" ]]; then
  echo "[gen-keys] Chaves já existem em $OUT (usa --force para regenerar)."
  exit 0
fi

echo "[gen-keys] Par RS256 (2048 bits) do auth para assinar JWT..."
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$OUT/private/auth-rs256.pem" 2>/dev/null
openssl pkey -in "$OUT/private/auth-rs256.pem" -pubout -out "$OUT/public/auth-rs256.pub.pem"

for signer in api-1 api-2 coordinator legacy-bank; do
  echo "[gen-keys] Par Ed25519 de $signer..."
  openssl genpkey -algorithm ED25519 -out "$OUT/private/$signer-ed25519.pem"
  # PEM SubjectPublicKeyInfo: readable by Python (cryptography) and Java (X509EncodedKeySpec)
  openssl pkey -in "$OUT/private/$signer-ed25519.pem" -pubout -out "$OUT/public/$signer-ed25519.pub.pem"
done

echo "[gen-keys] Chave de dados AES-256 do auth (cifragem em repouso)..."
openssl rand -out "$OUT/private/auth-data.key" 32

# Private keys: owner only (service containers run as root and can still read the bind mount).
chmod 600 "$OUT"/private/*
chmod 644 "$OUT"/public/*
echo "[gen-keys] Concluído."
