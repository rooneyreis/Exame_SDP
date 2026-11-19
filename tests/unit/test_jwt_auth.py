"""JWT RS256 issue/validate (common/jwt_auth.py)."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from common.jwt_auth import AUDIENCE, ISSUER, TokenError, TokenValidator, issue_token, key_id, public_jwk

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = key_id(KEY.public_key())
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def validator():
    return TokenValidator(keys={KID: KEY.public_key()})


def test_valid_token_has_all_claims():
    claims = validator().decode(issue_token(KEY, KID, "user-1", "cliente", "EU", 900))
    assert claims["sub"] == "user-1" and claims["role"] == "cliente" and claims["region"] == "EU"
    assert claims["iss"] == ISSUER and claims["aud"] == AUDIENCE
    assert claims["exp"] - claims["iat"] == 900 and claims["jti"]


def test_kid_is_in_the_header():
    assert jwt.get_unverified_header(issue_token(KEY, KID, "u", "cliente", "EU", 60))["kid"] == KID


def test_expired_token_is_rejected():
    token = issue_token(KEY, KID, "u", "cliente", "EU", 60, now=int(time.time()) - 3600)
    with pytest.raises(TokenError, match="expirado"):
        validator().decode(token)


def test_token_signed_by_another_key_is_rejected():
    token = issue_token(OTHER_KEY, KID, "u", "admin", "EU", 60)  # attacker reuses our kid
    with pytest.raises(TokenError, match="inválido"):
        validator().decode(token)


def test_unknown_kid_is_rejected():
    with pytest.raises(TokenError, match="kid desconhecido"):
        validator().decode(issue_token(KEY, "other-kid", "u", "cliente", "EU", 60))


def test_alg_none_is_rejected():
    token = jwt.encode({"sub": "u", "role": "admin"}, None, algorithm="none", headers={"kid": KID})
    with pytest.raises(TokenError, match="algoritmo"):
        validator().decode(token)


def test_wrong_audience_is_rejected():
    now = int(time.time())
    token = jwt.encode({"sub": "u", "role": "cliente", "iss": ISSUER, "aud": "other-app", "iat": now,
                        "exp": now + 60, "jti": "x"}, KEY, algorithm="RS256", headers={"kid": KID})
    with pytest.raises(TokenError):
        validator().decode(token)


def test_tampered_payload_is_rejected():
    header, payload, signature = issue_token(KEY, KID, "u", "cliente", "EU", 60).split(".")
    forged = jwt.utils.base64url_encode(b'{"sub":"u","role":"admin"}').decode()
    with pytest.raises(TokenError):
        validator().decode(f"{header}.{forged}.{signature}")


def test_public_jwk_round_trip():
    jwk = public_jwk(KEY.public_key())
    assert jwk["kid"] == KID and jwk["alg"] == "RS256" and "d" not in jwk  # never the private part
    token = issue_token(KEY, KID, "u", "cliente", "EU", 60)
    assert TokenValidator(keys={KID: jwt.PyJWK(jwk).key}).decode(token)["sub"] == "u"
