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
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from psycopg import errors
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from common.audit import AuditLog
from common.crypto import decrypt_field, encrypt_field
from common.jwt_auth import TokenValidator, auth_dependencies, client_ip, issue_token, key_id, public_jwk
from common.rbac import STAFF_ROLES, matrix
from common.logging import add_request_logging, log_extra, setup_logging

from . import validation
from .config import settings
from .schemas import (AdminBeneficiaryIn, ApproveKycRequest, BeneficiaryIn, BeneficiaryUpdate, LoginRequest,
                      RefreshRequest, RegisterRequest, StaffRequest, StatusChange, UserUpdate)

log = setup_logging("auth")
audit = AuditLog("auth")

# --- Keys -------------------------------------------------------------------
PRIVATE_KEY = serialization.load_pem_private_key(settings.jwt_private_key.read_bytes(), password=None)
PUBLIC_KEY = PRIVATE_KEY.public_key()
KID = key_id(PUBLIC_KEY)
DATA_KEY = settings.data_key.read_bytes()  # AES-256 key for data at rest (never stored in the DB)

validator = TokenValidator(keys={KID: PUBLIC_KEY})  # auth validates its own tokens locally


async def security_denied(claims: dict, permission: str, request: Request) -> None:
    """Every refused attempt by an authenticated user goes to the tamper-evident audit log."""
    log.warning(f"acesso negado: {claims.get('role')} -> {request.method} {request.url.path}")
    await audit.write("ACESSO_NEGADO", actor=claims.get("sub"), actor_role=claims.get("role"),
                      permission=permission, method=request.method, path=request.url.path,
                      ip=client_ip(request), result="NEGADO")


current_claims, require_role, require_permission = auth_dependencies(validator, on_denied=security_denied)


async def record(action: str, claims: dict, request: Request, result: str = "OK", **fields) -> None:
    """Audit-trail entry for an administrative/operational action."""
    await audit.write(action, actor=claims.get("sub"), actor_role=claims.get("role"),
                      ip=client_ip(request), result=result, **fields)

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
async def login(body: LoginRequest, request: Request):
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
            elif user["role"] not in ("cliente", *STAFF_ROLES):
                error = (status.HTTP_403_FORBIDDEN, "perfil sem acesso interativo")
            else:
                await conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = %s",
                                   (user["id"],))
                tokens = await issue_token_pair(conn, user)
        # the transaction is committed here, also when the login failed (counter update)

    if error:
        event = "CONTA_BLOQUEADA" if error[0] == status.HTTP_423_LOCKED else "LOGIN_FALHOU"
        await audit.write(event, email=email, reason=error[1], ip=client_ip(request), result="NEGADO")
        raise HTTPException(*error)
    log.info("login com sucesso", extra=log_extra(user_id=str(user["id"]), role=user["role"]))
    await audit.write("LOGIN_OK", actor=str(user["id"]), actor_role=user["role"], ip=client_ip(request), result="OK")
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
async def approve_kyc(user_id: uuid.UUID, request: Request, body: ApproveKycRequest | None = None,
                      claims: dict = Depends(require_permission("kyc:approve"))):
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
    await record("KYC_APROVADO", claims, request, target=str(user_id), iban=account.get("iban"),
                 before={"status": "PENDENTE_VERIFICACAO"}, after={"status": "ATIVA", "currency": currency})
    return {"user_id": str(user_id), "status": "ATIVA", "account": account}


@app.post("/admin/staff", status_code=status.HTTP_201_CREATED)
async def create_staff(body: StaffRequest, request: Request, claims: dict = Depends(require_permission("users:manage"))):
    user_id = uuid.uuid4()
    try:
        async with pool.connection() as conn:
            await conn.execute(
                """INSERT INTO users (id, full_name, email, phone, password_hash, region, role, status, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'ATIVA', %s)""",
                (user_id, body.full_name, body.email, body.phone, await hash_password(body.password),
                 body.region, body.role, claims["sub"]),
            )
    except errors.UniqueViolation:
        await record("UTILIZADOR_CRIADO", claims, request, result="FALHOU", email=body.email, reason="duplicado")
        raise HTTPException(status.HTTP_409_CONFLICT, "email ou telefone já registado")
    log.info("staff criado", extra=log_extra(user_id=str(user_id), role=body.role, admin=claims["sub"]))
    await record("UTILIZADOR_CRIADO", claims, request, target=str(user_id),
                 after={"email": body.email, "role": body.role, "status": "ATIVA"})
    return {"id": str(user_id), "role": body.role, "status": "ATIVA"}


def public_user(user: dict, with_sensitive: bool = False) -> dict:
    out = {k: user.get(k) for k in ("id", "full_name", "email", "phone", "region", "role", "status", "created_at",
                                    "updated_at", "failed_attempts", "locked_until", "created_by")}
    if with_sensitive:
        # Decrypted only here, for an authorised operator. In the DB they are AES-GCM ciphertext.
        aad = str(user["id"]).encode()
        out["document_id"] = decrypt_field(DATA_KEY, user["document_id_enc"], aad) if user["document_id_enc"] else None
        out["birth_date"] = decrypt_field(DATA_KEY, user["birth_date_enc"], aad) if user["birth_date_enc"] else None
    return out


@app.get("/admin/users")
async def list_users(status_filter: str | None = Query(None, alias="status"),
                     role: str | None = None, q: str | None = Query(None, max_length=80),
                     claims: dict = Depends(require_permission("users:read"))):
    where, args = ["role <> 'service'"], []
    if status_filter:
        where.append("status = %s"); args.append(status_filter)
    if role:
        where.append("role = %s"); args.append(role)
    if q:
        where.append("(full_name ILIKE %s OR email ILIKE %s OR phone ILIKE %s)"); args += [f"%{q}%"] * 3
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            f"SELECT * FROM users WHERE {' AND '.join(where)} ORDER BY created_at", args)).fetchall()
    return [public_user(r) for r in rows]


@app.get("/admin/users/{user_id}")
async def get_user(user_id: uuid.UUID, request: Request,
                   claims: dict = Depends(require_permission("users:read:sensitive"))):
    async with pool.connection() as conn:
        user = await (await conn.execute("SELECT * FROM users WHERE id = %s", (user_id,))).fetchone()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "utilizador não encontrado")
    # Consultar dados pessoais decifrados também fica registado.
    await record("DADOS_PESSOAIS_CONSULTADOS", claims, request, target=str(user_id))
    return public_user(user, with_sensitive=True)


# --- Administração de utilizadores (RBAC) ------------------------------------------------

@app.get("/admin/roles")
async def roles_matrix(claims: dict = Depends(require_permission("users:read"))):
    """Perfis e permissões em vigor (a fonte é common/rbac.py, aplicada no backend)."""
    return matrix()


async def load_user(conn, user_id) -> dict:
    user = await (await conn.execute("SELECT * FROM users WHERE id = %s FOR UPDATE", (user_id,))).fetchone()
    if user is None or user["role"] == "service":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "utilizador não encontrado")
    return user


async def other_active_admins(conn, user_id) -> int:
    row = await (await conn.execute(
        "SELECT count(*) AS n FROM users WHERE role = 'admin' AND status = 'ATIVA' AND id <> %s", (user_id,))).fetchone()
    return row["n"]


@app.patch("/admin/users/{user_id}")
async def update_user(user_id: uuid.UUID, body: UserUpdate, request: Request,
                      claims: dict = Depends(require_permission("users:manage"))):
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "nada para alterar")
    if "role" in changes and str(user_id) == claims["sub"]:
        await record("PERFIL_ALTERADO", claims, request, result="NEGADO", target=str(user_id), reason="o próprio perfil")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "não pode alterar o seu próprio perfil")
    try:
        async with pool.connection() as conn:
            async with conn.transaction():
                user = await load_user(conn, user_id)
                if "role" in changes:
                    if user["role"] not in STAFF_ROLES:
                        raise HTTPException(status.HTTP_409_CONFLICT,
                                            "o perfil de clientes não pode ser alterado (crie um acesso de equipa separado)")
                    if user["role"] == "admin" and changes["role"] != "admin" and await other_active_admins(conn, user_id) == 0:
                        raise HTTPException(status.HTTP_409_CONFLICT, "não é possível remover o último administrador ativo")
                before = {k: user[k] for k in changes}
                sets = ", ".join(f"{k} = %s" for k in changes)
                await conn.execute(f"UPDATE users SET {sets}, updated_at = now() WHERE id = %s", [*changes.values(), user_id])
                if "role" in changes and changes["role"] != user["role"]:
                    # Sessões antigas terminam: o novo perfil vale a partir do próximo login.
                    await conn.execute("UPDATE refresh_tokens SET revoked = true WHERE user_id = %s", (user_id,))
    except errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "email ou telefone já registado")
    action = "PERFIL_ALTERADO" if "role" in changes else "UTILIZADOR_EDITADO"
    await record(action, claims, request, target=str(user_id), before=before, after=changes)
    async with pool.connection() as conn:
        return public_user(await (await conn.execute("SELECT * FROM users WHERE id = %s", (user_id,))).fetchone())


TRANSITIONS = {   # action -> (estados de origem permitidos, novo estado)
    "block": ({"ATIVA"}, "BLOQUEADA"),
    "unblock": ({"BLOQUEADA", "ATIVA"}, "ATIVA"),          # também limpa o bloqueio por tentativas falhadas
    "deactivate": ({"ATIVA", "BLOQUEADA", "PENDENTE_VERIFICACAO"}, "DESATIVADA"),
    "reactivate": ({"DESATIVADA"}, "ATIVA"),
}


@app.post("/admin/users/{user_id}/status")
async def change_status(user_id: uuid.UUID, body: StatusChange, request: Request,
                        claims: dict = Depends(require_permission("users:manage"))):
    if str(user_id) == claims["sub"]:
        await record("ESTADO_ALTERADO", claims, request, result="NEGADO", target=str(user_id), reason="a própria conta")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "não pode alterar o estado da sua própria conta")
    allowed, new_status = TRANSITIONS[body.action]
    async with pool.connection() as conn:
        async with conn.transaction():
            user = await load_user(conn, user_id)
            if user["status"] not in allowed:
                raise HTTPException(status.HTTP_409_CONFLICT, f"ação '{body.action}' inválida no estado {user['status']}")
            if (user["role"] == "admin" and new_status != "ATIVA"
                    and await other_active_admins(conn, user_id) == 0):
                raise HTTPException(status.HTTP_409_CONFLICT, "não é possível bloquear o último administrador ativo")
            await conn.execute(
                "UPDATE users SET status = %s, updated_at = now(), "
                "failed_attempts = CASE WHEN %s = 'ATIVA' THEN 0 ELSE failed_attempts END, "
                "locked_until = CASE WHEN %s = 'ATIVA' THEN NULL ELSE locked_until END WHERE id = %s",
                (new_status, new_status, new_status, user_id))
            if new_status != "ATIVA":
                await conn.execute("UPDATE refresh_tokens SET revoked = true WHERE user_id = %s", (user_id,))
            updated = await (await conn.execute("SELECT * FROM users WHERE id = %s", (user_id,))).fetchone()
    await record("ESTADO_ALTERADO", claims, request, target=str(user_id), reason=body.reason,
                 before={"status": user["status"], "locked_until": user["locked_until"]},
                 after={"status": new_status, "action": body.action})
    return public_user(updated)


# --- Beneficiários (guardados no servidor) --------------------------------------------------

def beneficiary_out(b: dict) -> dict:
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in b.items()}


async def insert_beneficiary(owner_id, body, created_by) -> dict:
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                """INSERT INTO beneficiaries (id, owner_id, name, iban, nickname, favorite, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                (uuid.uuid4(), owner_id, body.name.strip(), body.iban, body.nickname, body.favorite, created_by))).fetchone()
    except errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "este IBAN já está nos beneficiários")
    return row


@app.get("/beneficiaries")
async def my_beneficiaries(claims: dict = Depends(require_permission("beneficiaries:manage:own"))):
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT * FROM beneficiaries WHERE owner_id = %s ORDER BY favorite DESC, name", (claims["sub"],))).fetchall()
    return [beneficiary_out(r) for r in rows]


@app.post("/beneficiaries", status_code=status.HTTP_201_CREATED)
async def add_my_beneficiary(body: BeneficiaryIn, request: Request,
                             claims: dict = Depends(require_permission("beneficiaries:manage:own"))):
    row = await insert_beneficiary(claims["sub"], body, claims["sub"])
    await record("BENEFICIARIO_CRIADO", claims, request, target=str(row["id"]), after={"iban": body.iban, "name": body.name})
    return beneficiary_out(row)


async def update_beneficiary(bid, body, owner_filter=None) -> tuple[dict, dict]:
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "nada para alterar")
    async with pool.connection() as conn:
        async with conn.transaction():
            old = await (await conn.execute("SELECT * FROM beneficiaries WHERE id = %s FOR UPDATE", (bid,))).fetchone()
            if old is None or (owner_filter and str(old["owner_id"]) != owner_filter):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "beneficiário não encontrado")
            sets = ", ".join(f"{k} = %s" for k in changes)
            new = await (await conn.execute(f"UPDATE beneficiaries SET {sets}, updated_at = now() WHERE id = %s RETURNING *",
                                            [*changes.values(), bid])).fetchone()
    return old, new


async def delete_beneficiary(bid, owner_filter=None) -> dict:
    async with pool.connection() as conn:
        old = await (await conn.execute("SELECT * FROM beneficiaries WHERE id = %s", (bid,))).fetchone()
        if old is None or (owner_filter and str(old["owner_id"]) != owner_filter):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "beneficiário não encontrado")
        await conn.execute("DELETE FROM beneficiaries WHERE id = %s", (bid,))
    return old


@app.patch("/beneficiaries/{bid}")
async def edit_my_beneficiary(bid: uuid.UUID, body: BeneficiaryUpdate, request: Request,
                              claims: dict = Depends(require_permission("beneficiaries:manage:own"))):
    old, new = await update_beneficiary(bid, body, owner_filter=claims["sub"])
    await record("BENEFICIARIO_EDITADO", claims, request, target=str(bid),
                 before={k: old[k] for k in body.model_dump(exclude_none=True)}, after=body.model_dump(exclude_none=True))
    return beneficiary_out(new)


@app.delete("/beneficiaries/{bid}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_my_beneficiary(bid: uuid.UUID, request: Request,
                                claims: dict = Depends(require_permission("beneficiaries:manage:own"))):
    old = await delete_beneficiary(bid, owner_filter=claims["sub"])
    await record("BENEFICIARIO_REMOVIDO", claims, request, target=str(bid), before={"iban": old["iban"], "name": old["name"]})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/admin/beneficiaries")
async def list_beneficiaries(owner_id: uuid.UUID | None = None,
                             claims: dict = Depends(require_permission("beneficiaries:read:any"))):
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            """SELECT b.*, u.full_name AS owner_name, u.email AS owner_email FROM beneficiaries b
               JOIN users u ON u.id = b.owner_id
               WHERE (%s::uuid IS NULL OR b.owner_id = %s) ORDER BY u.full_name, b.name""",
            (owner_id, owner_id))).fetchall()
    return [beneficiary_out(r) for r in rows]


@app.post("/admin/beneficiaries", status_code=status.HTTP_201_CREATED)
async def add_beneficiary_for_client(body: AdminBeneficiaryIn, request: Request,
                                     claims: dict = Depends(require_permission("beneficiaries:manage:any"))):
    async with pool.connection() as conn:
        owner = await (await conn.execute("SELECT role, status FROM users WHERE id = %s", (body.owner_id,))).fetchone()
    if owner is None or owner["role"] != "cliente":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cliente não encontrado")
    row = await insert_beneficiary(body.owner_id, body, claims["sub"])
    await record("BENEFICIARIO_CRIADO", claims, request, target=str(row["id"]), owner=str(body.owner_id),
                 after={"iban": body.iban, "name": body.name})
    return beneficiary_out(row)


@app.patch("/admin/beneficiaries/{bid}")
async def edit_beneficiary_for_client(bid: uuid.UUID, body: BeneficiaryUpdate, request: Request,
                                      claims: dict = Depends(require_permission("beneficiaries:manage:any"))):
    old, new = await update_beneficiary(bid, body)
    await record("BENEFICIARIO_EDITADO", claims, request, target=str(bid), owner=str(old["owner_id"]),
                 before={k: old[k] for k in body.model_dump(exclude_none=True)}, after=body.model_dump(exclude_none=True))
    return beneficiary_out(new)


@app.delete("/admin/beneficiaries/{bid}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_beneficiary_for_client(bid: uuid.UUID, request: Request,
                                        claims: dict = Depends(require_permission("beneficiaries:manage:any"))):
    old = await delete_beneficiary(bid)
    await record("BENEFICIARIO_REMOVIDO", claims, request, target=str(bid), owner=str(old["owner_id"]),
                 before={"iban": old["iban"], "name": old["name"]})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
