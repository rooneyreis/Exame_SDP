"""auth service: registration, KYC, login, token refresh/logout, JWKS and staff management.

It is the ONLY service holding the RS256 private key. Everyone else validates the
tokens it issues with the public key from /.well-known/jwks.json.
"""
import asyncio
import hashlib
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives import serialization
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from psycopg import errors
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from common.audit import AuditLog
from common.crypto import decrypt_field, encrypt_field
from common.jwt_auth import TokenValidator, auth_dependencies, issue_token, key_id, public_jwk
from common.logging import add_request_logging, log_extra, setup_logging

from . import validation
from .config import settings
from .schemas import ApproveKycRequest, LoginRequest, RefreshRequest, RegisterRequest, StaffRequest

log = setup_logging("auth")
audit = AuditLog("auth")

# --- Keys -------------------------------------------------------------------
PRIVATE_KEY = serialization.load_pem_private_key(settings.jwt_private_key.read_bytes(), password=None)
PUBLIC_KEY = PRIVATE_KEY.public_key()
KID = key_id(PUBLIC_KEY)
DATA_KEY = settings.data_key.read_bytes()  # AES-256 key for data at rest (never stored in the DB)

validator = TokenValidator(keys={KID: PUBLIC_KEY})  # auth validates its own tokens locally
current_claims, require_role = auth_dependencies(validator)

# Argon2id with the library defaults (time_cost=3, memory_cost=64 MiB, parallelism=4).
hasher = PasswordHasher()
# Used when the email does not exist, so the response time does not reveal it.
DUMMY_HASH = hasher.hash("timing-equaliser-not-a-real-password")

pool = AsyncConnectionPool(
    settings.db_dsn, open=False, min_size=1, max_size=10,
    kwargs={"row_factory": dict_row},
    check=AsyncConnectionPool.check_connection,  # discard connections broken by a DB restart
    reconnect_timeout=24 * 3600,                 # keep retrying instead of giving up after 5 min
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open(wait=False)  # does not block start-up if pg-core is still booting
    log.info(f"auth a arrancar; kid={KID}")
    yield
    await pool.close()


app = FastAPI(title="Global-Scale auth", lifespan=lifespan)
add_request_logging(app, log)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    """Refresh tokens are stored only as SHA-256: a DB leak does not leak usable tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


async def hash_password(password: str) -> str:
    # Argon2 is CPU-bound and deliberately slow: run it in a thread so the asyncio
    # event loop keeps serving other requests meanwhile.
    return await asyncio.to_thread(hasher.hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    try:
        return await asyncio.to_thread(hasher.verify, password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


async def issue_token_pair(conn, user: dict) -> dict:
    access = issue_token(PRIVATE_KEY, KID, str(user["id"]), user["role"], user["region"],
                         settings.access_ttl_seconds)
    refresh = secrets.token_urlsafe(32)
    await conn.execute(
        "INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at) VALUES (%s, %s, %s, %s)",
        (uuid.uuid4(), user["id"], token_hash(refresh), now_utc() + timedelta(days=settings.refresh_ttl_days)),
    )
    return {"access_token": access, "token_type": "bearer", "expires_in": settings.access_ttl_seconds,
            "refresh_token": refresh}


# --- Public endpoints ----------------------------------------------------------

@app.get("/health")
async def health():
    try:
        async with pool.connection(timeout=3) as conn:
            await conn.execute("SELECT 1")
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, {"status": "degradado", "db": repr(exc)})
    return {"status": "ok", "db": "ok", "kid": KID}


@app.get("/.well-known/jwks.json")
async def jwks():
    return {"keys": [public_jwk(PUBLIC_KEY)]}


@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest):
    if not validation.is_adult(body.birth_date, date.today()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "é necessário ter pelo menos 18 anos")

    user_id = uuid.uuid4()
    aad = str(user_id).encode()  # binds each ciphertext to its owner
    password_hash = await hash_password(body.password)
    try:
        async with pool.connection() as conn:
            await conn.execute(
                """INSERT INTO users (id, full_name, email, phone, password_hash, region,
                                      document_id_enc, birth_date_enc, role, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'cliente', 'PENDENTE_VERIFICACAO')""",
                (user_id, body.full_name, body.email, body.phone, password_hash, body.region,
                 encrypt_field(DATA_KEY, body.document_id, aad),
                 encrypt_field(DATA_KEY, body.birth_date.isoformat(), aad)),
            )
    except errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "email ou telefone já registado")

    log.info("cliente registado, a aguardar KYC", extra=log_extra(user_id=str(user_id), region=body.region))
    await audit.write("REGISTO", user_id=str(user_id), region=body.region)
    return {"id": str(user_id), "status": "PENDENTE_VERIFICACAO", "region": body.region}


@app.post("/auth/login")
async def login(body: LoginRequest):
    now = now_utc()
    email = body.email.lower()
    error: tuple[int, str] | None = None
    tokens = None

    async with pool.connection() as conn:
        # FOR UPDATE serialises concurrent logins of the same user, so parallel
        # attempts cannot bypass the failed-attempts counter.
        async with conn.transaction():
            user = await (await conn.execute(
                "SELECT * FROM users WHERE email = %s FOR UPDATE", (email,))).fetchone()

            if user is None:
                await verify_password(DUMMY_HASH, body.password)  # same time as a real check
                error = (status.HTTP_401_UNAUTHORIZED, "credenciais inválidas")
            elif validation.is_locked(user["locked_until"], now):
                error = (status.HTTP_423_LOCKED, f"conta bloqueada até {user['locked_until'].isoformat()}")
            elif not await verify_password(user["password_hash"], body.password):
                attempts, locked_until = validation.after_failed_login(user["failed_attempts"], now)
                await conn.execute("UPDATE users SET failed_attempts = %s, locked_until = %s WHERE id = %s",
                                   (attempts, locked_until, user["id"]))
                if locked_until:
                    log.warning("conta bloqueada após 5 tentativas falhadas", extra=log_extra(user_id=str(user["id"])))
                    error = (status.HTTP_423_LOCKED, "5 tentativas falhadas: conta bloqueada por 15 minutos")
                else:
                    error = (status.HTTP_401_UNAUTHORIZED, "credenciais inválidas")
            elif user["status"] != "ATIVA":
                error = (status.HTTP_403_FORBIDDEN, f"conta não ativa (estado: {user['status']})")
            else:
                await conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = %s",
                                   (user["id"],))
                tokens = await issue_token_pair(conn, user)
        # the transaction is committed here, also when the login failed (counter update)

    if error:
        event = "CONTA_BLOQUEADA" if error[0] == status.HTTP_423_LOCKED else "LOGIN_FALHOU"
        await audit.write(event, email=email, reason=error[1])
        raise HTTPException(*error)
    log.info("login com sucesso", extra=log_extra(user_id=str(user["id"]), role=user["role"]))
    await audit.write("LOGIN_OK", user_id=str(user["id"]), role=user["role"])
    return tokens


@app.post("/auth/refresh")
async def refresh(body: RefreshRequest):
    error = None
    async with pool.connection() as conn:
        async with conn.transaction():
            row = await (await conn.execute(
                """SELECT rt.id AS token_id, rt.revoked, rt.expires_at, u.*
                   FROM refresh_tokens rt JOIN users u ON u.id = rt.user_id
                   WHERE rt.token_hash = %s FOR UPDATE OF rt""",
                (token_hash(body.refresh_token),))).fetchone()

            if row is None:
                error = "refresh token inválido"
            elif row["revoked"]:
                # A revoked token used again means it was probably stolen: revoke every
                # token of this user (refresh token reuse detection).
                await conn.execute("UPDATE refresh_tokens SET revoked = true WHERE user_id = %s", (row["id"],))
                log.warning("reutilização de refresh token revogado: todas as sessões revogadas",
                            extra=log_extra(user_id=str(row["id"])))
                error = "refresh token revogado"
            elif row["expires_at"] <= now_utc():
                error = "refresh token expirado"
            elif row["status"] != "ATIVA":
                error = "conta não ativa"
            else:
                # Rotation: the old token stops working, a new pair is issued.
                await conn.execute("UPDATE refresh_tokens SET revoked = true WHERE id = %s", (row["token_id"],))
                tokens = await issue_token_pair(conn, row)
    if error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, error)
    return tokens


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, claims: dict = Depends(current_claims)):
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE refresh_tokens SET revoked = true WHERE token_hash = %s AND user_id = %s",
            (token_hash(body.refresh_token), claims["sub"]),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Staff endpoints -------------------------------------------------------------

async def create_account_via_api(user_id: str, region: str, currency: str) -> dict | None:
    """Asks the api to create the account in the shard of the region.
    Authenticates with a short-lived service token (role=service). Tries each api instance."""
    token = issue_token(PRIVATE_KEY, KID, "auth", "service", None, settings.service_token_ttl_seconds)
    payload = {"user_id": user_id, "region": region, "currency": currency}
    async with httpx.AsyncClient(verify=settings.ca_file, timeout=5) as client:
        for base in settings.api_urls:
            try:
                response = await client.post(f"{base}/internal/accounts", json=payload,
                                             headers={"Authorization": f"Bearer {token}"})
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                log.warning(f"criação de conta falhou em {base}: {exc!r}")
    return None


@app.post("/admin/users/{user_id}/approve-kyc")
async def approve_kyc(user_id: uuid.UUID, body: ApproveKycRequest | None = None,
                      claims: dict = Depends(require_role("operador"))):
    async with pool.connection() as conn:
        user = await (await conn.execute("SELECT * FROM users WHERE id = %s", (user_id,))).fetchone()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "utilizador não encontrado")
    if user["role"] != "cliente" or user["status"] != "PENDENTE_VERIFICACAO":
        raise HTTPException(status.HTTP_409_CONFLICT, f"utilizador não está pendente (estado: {user['status']})")

    currency = (body.currency if body and body.currency else None) or validation.default_currency(user["region"])
    # The account is created first. If the api is down, the user stays pending and the
    # operator can retry (/internal/accounts is idempotent per user).
    account = await create_account_via_api(str(user_id), user["region"], currency)
    if account is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "serviço de contas indisponível: KYC não aprovado, tente novamente")

    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE users SET status = 'ATIVA' WHERE id = %s AND status = 'PENDENTE_VERIFICACAO'", (user_id,))
    log.info("KYC aprovado", extra=log_extra(user_id=str(user_id), operador=claims["sub"], iban=account.get("iban")))
    await audit.write("KYC_APROVADO", user_id=str(user_id), iban=account.get("iban"), operador=claims["sub"])
    return {"user_id": str(user_id), "status": "ATIVA", "account": account}


@app.post("/admin/staff", status_code=status.HTTP_201_CREATED)
async def create_staff(body: StaffRequest, claims: dict = Depends(require_role("admin"))):
    user_id = uuid.uuid4()
    try:
        async with pool.connection() as conn:
            await conn.execute(
                """INSERT INTO users (id, full_name, email, phone, password_hash, region, role, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'ATIVA')""",
                (user_id, body.full_name, body.email, body.phone, await hash_password(body.password),
                 body.region, body.role),
            )
    except errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "email ou telefone já registado")
    log.info("staff criado", extra=log_extra(user_id=str(user_id), role=body.role, admin=claims["sub"]))
    await audit.write("STAFF_CRIADO", user_id=str(user_id), role=body.role, admin=claims["sub"])
    return {"id": str(user_id), "role": body.role, "status": "ATIVA"}


def public_user(user: dict, with_sensitive: bool = False) -> dict:
    out = {k: user[k] for k in ("id", "full_name", "email", "phone", "region", "role", "status", "created_at")}
    if with_sensitive:
        # Decrypted only here, for an authorised operator. In the DB they are AES-GCM ciphertext.
        aad = str(user["id"]).encode()
        out["document_id"] = decrypt_field(DATA_KEY, user["document_id_enc"], aad) if user["document_id_enc"] else None
        out["birth_date"] = decrypt_field(DATA_KEY, user["birth_date_enc"], aad) if user["birth_date_enc"] else None
    return out


@app.get("/admin/users")
async def list_users(status_filter: str | None = Query(None, alias="status"),
                     claims: dict = Depends(require_role("operador", "admin"))):
    async with pool.connection() as conn:
        if status_filter:
            rows = await (await conn.execute(
                "SELECT * FROM users WHERE status = %s ORDER BY created_at", (status_filter,))).fetchall()
        else:
            rows = await (await conn.execute("SELECT * FROM users ORDER BY created_at")).fetchall()
    return [public_user(r) for r in rows]


@app.get("/admin/users/{user_id}")
async def get_user(user_id: uuid.UUID, claims: dict = Depends(require_role("operador", "admin"))):
    async with pool.connection() as conn:
        user = await (await conn.execute("SELECT * FROM users WHERE id = %s", (user_id,))).fetchone()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "utilizador não encontrado")
    return public_user(user, with_sensitive=True)
