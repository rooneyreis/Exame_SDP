"""AES-256-GCM field encryption (data at rest)."""
import os

import pytest
from cryptography.exceptions import InvalidTag

from common.crypto import NONCE_SIZE, decrypt_field, encrypt_field, sha256_hex

KEY = os.urandom(32)
AAD = b"11111111-0000-4000-8000-000000000001"


def test_round_trip():
    blob = encrypt_field(KEY, "PT1234567", AAD)
    assert decrypt_field(KEY, blob, AAD) == "PT1234567"


def test_ciphertext_does_not_contain_plaintext():
    assert b"PT1234567" not in encrypt_field(KEY, "PT1234567", AAD)


def test_random_nonce_makes_each_ciphertext_different():
    a, b = encrypt_field(KEY, "x", AAD), encrypt_field(KEY, "x", AAD)
    assert a != b and a[:NONCE_SIZE] != b[:NONCE_SIZE]


def test_tampered_ciphertext_is_detected():
    blob = bytearray(encrypt_field(KEY, "PT1234567", AAD))
    blob[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        decrypt_field(KEY, bytes(blob), AAD)


def test_ciphertext_moved_to_another_user_is_rejected():
    blob = encrypt_field(KEY, "PT1234567", AAD)
    with pytest.raises(InvalidTag):
        decrypt_field(KEY, blob, b"22222222-0000-4000-8000-000000000001")


def test_wrong_key_is_rejected():
    with pytest.raises(InvalidTag):
        decrypt_field(os.urandom(32), encrypt_field(KEY, "x", AAD), AAD)


def test_sha256_hex():
    assert sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
