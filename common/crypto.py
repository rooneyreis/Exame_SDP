"""Cryptographic helpers shared by the services.

- AES-256-GCM field encryption (data at rest, section 7.5)
- SHA-256 helpers
(Ed25519 signatures and canonical JSON are added in Phase 4.)
"""
import hashlib
import os

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
