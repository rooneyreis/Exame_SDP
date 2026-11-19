"""Canonical JSON + SHA-256 + Ed25519 signed requests (common/crypto.py)."""
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from common.crypto import canonical_json, check_signed_request, sign, signed_headers, verify_signature

KEY = Ed25519PrivateKey.generate()
TRUSTED = {"api-1": KEY.public_key()}
PAYLOAD = {"tx_id": "t", "amount": "100.00", "from_iban": "GS-EU-00000001", "to_iban": "GS-AM-00000001"}


def lower(headers):
    return {k.lower(): v for k, v in headers.items()}


def test_valid_signed_request():
    body = canonical_json(PAYLOAD)
    assert check_signed_request(body, lower(signed_headers(KEY, "api-1", body)), TRUSTED) == (True, "ok")


def test_amount_changed_after_signing_is_detected():
    body = canonical_json(PAYLOAD)
    headers = lower(signed_headers(KEY, "api-1", body))
    tampered = canonical_json({**PAYLOAD, "amount": "9999.00"})
    ok, reason = check_signed_request(tampered, headers, TRUSTED)
    assert not ok and "SHA-256" in reason


def test_attacker_recomputes_sha256_but_cannot_sign():
    body = canonical_json(PAYLOAD)
    headers = lower(signed_headers(KEY, "api-1", body))
    tampered = canonical_json({**PAYLOAD, "amount": "9999.00"})
    headers["x-payload-sha256"] = __import__("hashlib").sha256(tampered).hexdigest()
    ok, reason = check_signed_request(tampered, headers, TRUSTED)
    assert not ok and "assinatura" in reason


def test_signature_by_untrusted_key_is_rejected():
    body = canonical_json(PAYLOAD)
    headers = lower(signed_headers(Ed25519PrivateKey.generate(), "api-1", body))  # claims to be api-1
    assert check_signed_request(body, headers, TRUSTED)[0] is False


def test_unknown_signer_is_rejected():
    body = canonical_json(PAYLOAD)
    ok, reason = check_signed_request(body, lower(signed_headers(KEY, "intruso", body)), TRUSTED)
    assert not ok and "desconhecido" in reason


def test_non_canonical_body_is_rejected():
    body = b'{"amount": "100.00"}'          # spaces: not canonical
    ok, reason = check_signed_request(body, lower(signed_headers(KEY, "api-1", body)), TRUSTED)
    assert not ok and "canónico" in reason


def test_sign_verify_round_trip():
    assert verify_signature(KEY.public_key(), b"x", sign(KEY, b"x"))
    assert not verify_signature(KEY.public_key(), b"y", sign(KEY, b"x"))
    assert not verify_signature(KEY.public_key(), b"x", "not-base64!!")
