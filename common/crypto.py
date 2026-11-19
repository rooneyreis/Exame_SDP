"""Cryptographic helpers shared by the services.

- AES-256-GCM field encryption (data at rest, section 7.5)
- SHA-256 and canonical JSON
- Ed25519 signatures of messages between services (integrity + origin)
"""
import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12  # 96-bit nonce, the size recommended for GCM


def encrypt_field(key: bytes, plaintext: str, associated_data: bytes) -> bytes:
    """Encrypts one value. Output: nonce || ciphertext+tag.

    associated_data is authenticated but not encrypted. We pass the owner's user id,
    so a ciphertext copied into another user's row fails to decrypt.
    """
    nonce = os.urandom(NONCE_SIZE)  # never reuse a nonce with the same key
    return nonce + AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), associated_data)


def decrypt_field(key: bytes, blob: bytes, associated_data: bytes) -> str:
    """Reverses encrypt_field. Raises cryptography.exceptions.InvalidTag if the data,
    the key or the associated data do not match (tampering detected)."""
    nonce, ciphertext = blob[:NONCE_SIZE], blob[NONCE_SIZE:]
    return AESGCM(key).decrypt(nonce, ciphertext, associated_data).decode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj) -> bytes:
    """Deterministic JSON: sorted keys, no spaces, UTF-8. The same object always gives
    the same bytes, which is required before hashing or signing it."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


# --- Ed25519 -----------------------------------------------------------------

def load_ed25519_private(path: str | Path) -> Ed25519PrivateKey:
    return serialization.load_pem_private_key(Path(path).read_bytes(), password=None)


def load_ed25519_public(path: str | Path) -> Ed25519PublicKey:
    return serialization.load_pem_public_key(Path(path).read_bytes())


def load_trusted_signers(directory: str | Path, names: list[str]) -> dict[str, Ed25519PublicKey]:
    """Public keys of the signers we trust, from <dir>/<name>-ed25519.pub.pem."""
    return {name: load_ed25519_public(Path(directory) / f"{name}-ed25519.pub.pem") for name in names}


def sign(private_key: Ed25519PrivateKey, data: bytes) -> str:
    return base64.b64encode(private_key.sign(data)).decode()


def verify_signature(public_key: Ed25519PublicKey, data: bytes, signature_b64: str) -> bool:
    try:
        public_key.verify(base64.b64decode(signature_b64, validate=True), data)
        return True
    except (InvalidSignature, ValueError):
        return False


def signed_headers(private_key: Ed25519PrivateKey, signer: str, body: bytes) -> dict[str, str]:
    """Headers sent with every signed request (api -> coordinator)."""
    return {
        "Content-Type": "application/json",
        "X-Payload-SHA256": sha256_hex(body),
        "X-Signature": sign(private_key, body),
        "X-Signer": signer,
    }


def check_signed_request(body: bytes, headers, trusted: dict[str, Ed25519PublicKey]) -> tuple[bool, str]:
    """Verifies a signed request. Returns (ok, reason). Checks, in order:
    known signer, canonical body, SHA-256 of the body, Ed25519 signature."""
    signer = headers.get("x-signer")
    if signer not in trusted:
        return False, f"assinante desconhecido: {signer!r}"
    try:
        if canonical_json(json.loads(body)) != body:
            return False, "payload não está em JSON canónico"
    except ValueError:
        return False, "payload não é JSON"
    if headers.get("x-payload-sha256") != sha256_hex(body):
        return False, "SHA-256 do payload não corresponde (conteúdo alterado)"
    if not verify_signature(trusted[signer], body, headers.get("x-signature") or ""):
        return False, "assinatura Ed25519 inválida"
    return True, "ok"
