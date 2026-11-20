"""JWT RS256: issuing (auth only) and decentralised validation (every service).

Only auth has the private key. Every other service validates tokens locally with the
public key published at /.well-known/jwks.json, kept in a cache. If auth goes down,
tokens already issued keep being accepted until they expire.
"""
import asyncio
import base64
import hashlib
import json
import logging
import time
import uuid

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ISSUER = "auth.global.local"
AUDIENCE = "global-scale"
ALGORITHM = "RS256"

log = logging.getLogger("jwt")


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def key_id(public_key: RSAPublicKey) -> str:
    """RFC 7638 thumbprint: SHA-256 of the canonical JWK (e, kty, n)."""
    numbers = public_key.public_numbers()
    canonical = json.dumps(
        {"e": _b64url_uint(numbers.e), "kty": "RSA", "n": _b64url_uint(numbers.n)},
        separators=(",", ":"), sort_keys=True,
    )
    return base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b"=").decode()


def public_jwk(public_key: RSAPublicKey) -> dict:
    numbers = public_key.public_numbers()
    return {
        "kty": "RSA", "use": "sig", "alg": ALGORITHM, "kid": key_id(public_key),
        "n": _b64url_uint(numbers.n), "e": _b64url_uint(numbers.e),
    }


def issue_token(private_key, kid: str, sub: str, role: str, region: str | None, ttl_seconds: int,
                now: int | None = None) -> str:
    now = int(time.time()) if now is None else now
    claims = {
        "sub": sub, "role": role, "region": region,
        "iss": ISSUER, "aud": AUDIENCE,
        "iat": now, "exp": now + ttl_seconds, "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, private_key, algorithm=ALGORITHM, headers={"kid": kid})


class TokenError(Exception):
    pass


class TokenValidator:
    """Validates tokens with a set of public keys indexed by kid.

    keys:      known keys (auth uses its own public key directly)
    jwks_url:  where to (re)load the keys from (api, coordinator)
    """

    def __init__(self, keys: dict | None = None, jwks_url: str | None = None,
                 ca_file: str | None = None, refresh_seconds: int = 600):
        self._keys: dict = dict(keys or {})
        self.jwks_url = jwks_url
        self.ca_file = ca_file
        self.refresh_seconds = refresh_seconds
        self.last_refresh: float | None = None

    @property
    def kids(self) -> list[str]:
        return list(self._keys)

    def decode(self, token: str) -> dict:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise TokenError(f"token mal formado: {exc}") from exc
        if header.get("alg") != ALGORITHM:
            raise TokenError("algoritmo não permitido")  # blocks "alg": "none" / HS256 tricks
        key = self._keys.get(header.get("kid"))
        if key is None:
            raise TokenError("kid desconhecido")
        try:
            return jwt.decode(
                token, key, algorithms=[ALGORITHM], audience=AUDIENCE, issuer=ISSUER,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenError("token expirado") from exc
        except jwt.PyJWTError as exc:
            raise TokenError(f"token inválido: {exc}") from exc

    async def refresh_jwks(self) -> bool:
        """Downloads the JWKS. On failure keeps the cached keys (auth may be down)."""
        try:
            async with httpx.AsyncClient(verify=self.ca_file, timeout=5) as client:
                response = await client.get(self.jwks_url)
                response.raise_for_status()
            keys = {k["kid"]: jwt.PyJWK(k).key for k in response.json()["keys"]}
        except Exception as exc:  # network error, auth down, bad JSON...
            log.warning(f"JWKS indisponível ({exc!r}); a manter {len(self._keys)} chave(s) em cache")
            return False
        self._keys = keys
        self.last_refresh = time.time()
        log.info(f"JWKS atualizado: kids={list(keys)}")
        return True

    async def refresh_forever(self) -> None:
        """Background task: first load retries every 2 s, then refresh every refresh_seconds."""
        while True:
            ok = await self.refresh_jwks()
            await asyncio.sleep(self.refresh_seconds if ok or self._keys else 2)


def client_ip(request: Request) -> str | None:
    """Real client IP. nginx sets X-Forwarded-For and Uvicorn (--proxy-headers, trusting only
    nginx's IP) puts it in request.client, so it cannot be spoofed by the client."""
    return request.client.host if request.client else None


def auth_dependencies(validator: TokenValidator, on_denied=None):
    """Builds the FastAPI dependencies current_claims, require_role(*roles) and
    require_permission(permission). on_denied(claims, permission, request) is awaited
    whenever an authenticated user is refused (security log)."""
    from .rbac import has_permission  # local import keeps the module light for unit tests

    bearer = HTTPBearer(auto_error=False)

    async def current_claims(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
        if creds is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token em falta",
                                headers={"WWW-Authenticate": "Bearer"})
        try:
            return validator.decode(creds.credentials)
        except TokenError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc),
                                headers={"WWW-Authenticate": "Bearer"}) from exc

    def require_role(*roles: str):
        async def check(request: Request, claims: dict = Depends(current_claims)) -> dict:
            if claims.get("role") not in roles:
                if on_denied:
                    await on_denied(claims, f"role:{'|'.join(roles)}", request)
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"requer role: {', '.join(roles)}")
            return claims
        return check

    def require_permission(*permissions: str):
        """Passes if the caller's role has ANY of the given permissions (checked server-side)."""
        async def check(request: Request, claims: dict = Depends(current_claims)) -> dict:
            if not any(has_permission(claims.get("role"), p) for p in permissions):
                if on_denied:
                    await on_denied(claims, "|".join(permissions), request)
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"sem permissão: {' ou '.join(permissions)}")
            return claims
        return check

    return current_claims, require_role, require_permission
