"""Public API (two instances, api-1 and api-2, behind nginx).

- Validates JWTs LOCALLY with the auth public key (JWKS kept in cache): if auth is
  down, tokens already issued keep working.
- Routes every account to its shard by the IBAN prefix / the user's region (common/db.py).
- Returns X-Served-By so the load balancing is visible.
(Transfers and admin endpoints are added in Phases 4 and 6.)
"""
import asyncio
import os
from contextlib import asynccontextmanager as _acm
import ssl
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import psycopg
import psycopg_pool
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from common import custody, limits
from common.audit import AuditLog, verify_chain
from common.crypto import canonical_json, load_ed25519_private, signed_headers
from common.db import REGIONS, SHARD_NODES, ShardRouter, is_valid_iban, make_pool, region_of_iban, shard_conninfo
from common.jwt_auth import TokenValidator, auth_dependencies, client_ip
from common.rbac import has_permission
from common.logging import add_request_logging, log_extra, setup_logging, tx_id_var
from common.reports import read_report
from common.reports import record as record_report
from common.transfers import transfer_tx_id

from .config import settings
from .schemas import CashOperation, ChaosRequest, CreateAccountRequest, TransferRequest

log = setup_logging(settings.instance_id)
audit = AuditLog(settings.instance_id, settings.audit_dir)

validator = TokenValidator(jwks_url=settings.jwks_url, ca_file=settings.ca_file,
                           refresh_seconds=settings.jwks_refresh_seconds)


async def security_denied(claims: dict, permission: str, request: Request) -> None:
    """Tentativas recusadas (URL ou chamada direta à API) ficam na auditoria encadeada."""
    log.warning(f"acesso negado: {claims.get('role')} -> {request.method} {request.url.path}")
    await audit.write("ACESSO_NEGADO", actor=claims.get("sub"), actor_role=claims.get("role"),
                      permission=permission, method=request.method, path=request.url.path,
                      ip=client_ip(request), result="NEGADO")


current_claims, require_role, require_permission = auth_dependencies(validator, on_denied=security_denied)


async def record(action: str, claims: dict, request: Request | None, result: str = "OK", **fields) -> None:
    await audit.write(action, actor=claims.get("sub"), actor_role=claims.get("role"),
                      ip=client_ip(request) if request else None, result=result, **fields)

shards = ShardRouter(
    {r: shard_conninfo(r, settings.db_user, settings.db_password, settings.ca_file) for r in REGIONS},
    # read-only endpoints may be served by the replica while the primary is down
    {r: shard_conninfo(r, settings.db_user, settings.db_password, settings.ca_file, read_only=True) for r in REGIONS})
core = make_pool(
    f"host=pg-core.global.local dbname=coordinator user={settings.db_user} password={settings.db_password} "
    f"sslmode=verify-full sslrootcert={settings.ca_file} connect_timeout=3", max_size=5)

SIGNING_KEY = load_ed25519_private(settings.signing_key)
# Long read timeout: a transfer may be paused by the chaos mode pause_after_prepare.
coordinator = httpx.AsyncClient(base_url=settings.coordinator_url,
                                verify=ssl.create_default_context(cafile=settings.ca_file),
                                timeout=httpx.Timeout(90, connect=3),
                                limits=httpx.Limits(max_connections=50))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await shards.open()
    await core.open(wait=False)
    jwks_task = asyncio.create_task(validator.refresh_forever())
    log.info(f"{settings.instance_id} a arrancar")
    yield
    jwks_task.cancel()
    await shards.close()
    await core.close()


app = FastAPI(title=f"Global-Scale API ({settings.instance_id})", lifespan=lifespan)
add_request_logging(app, log)


@app.exception_handler(psycopg_pool.PoolTimeout)
@app.exception_handler(psycopg.OperationalError)
async def database_unavailable(request, exc):
    """A shard/pg-core that is down (or in the middle of a failover) gives 503, not 500."""
    log.warning(f"base de dados indisponível: {exc!r}")
    return JSONResponse(status_code=503, content={"detail": "base de dados indisponível, tente novamente"})


@app.middleware("http")
async def served_by(request, call_next):
    response = await call_next(request)
    response.headers["X-Served-By"] = settings.instance_id
    return response


# --- helpers -------------------------------------------------------------------

@_acm
async def read_connection(region: str):
    """Connection for READ-ONLY queries: the primary (fresh data) if it answers within 2 s,
    otherwise the replica (target_session_attrs=any). So balances and statements stay
    available while a shard primary is down, and are never stale while it is up."""
    pool = shards.for_region(region)
    try:
        conn = await pool.getconn(timeout=2)
    except psycopg_pool.PoolTimeout:
        log.warning(f"primário do shard {region} indisponível: leitura servida pela réplica")
        pool = shards.for_region(region, read=True)
        conn = await pool.getconn()
    try:
        yield conn
    finally:
        await pool.putconn(conn)

def account_out(row: dict) -> dict:
    out = {
        "iban": row["iban"], "user_id": str(row["user_id"]), "region": region_of_iban(row["iban"]),
        "currency": row["currency"], "balance": f"{row['balance']:.2f}", "status": row["status"],
        "daily_limit": f"{row['daily_limit']:.2f}" if row.get("daily_limit") is not None else None,
        "created_at": row.get("created_at"), "closed_at": row.get("closed_at"),
        "region_unavailable": bool(row.get("unavailable")),
    }
    if row.get("unavailable"):
        # Region totally down: "balance" is the amount held in custody in other shards (usable now).
        out["held_in"] = {r: f"{b:.2f}" for r, b in row["held_in"].items()}
    return out


# --- region totally down: account directory + custody ------------------------------------

ANY_NODE = {r: shard_conninfo(r, settings.db_user, settings.db_password, settings.ca_file, read_only=True)
            for r in REGIONS}
_region_state: dict[str, tuple[float, bool]] = {}
REGION_STATE_SECONDS = 5


async def region_down(region: str, fresh: bool = False) -> bool:
    """True only when NO node of the region answers (primary AND replica). Cached for a few
    seconds, so a region that is down does not cost a connection timeout on every request.
    fresh=True ignores the cache (after a read failed: the region may have just gone down)."""
    cached = _region_state.get(region)
    if cached and not fresh and time.monotonic() - cached[0] < REGION_STATE_SECONDS:
        return cached[1]
    try:
        async with await psycopg.AsyncConnection.connect(ANY_NODE[region]) as conn:
            await conn.execute("SELECT 1")
        down = False
    except psycopg.OperationalError:
        down = True
    _region_state[region] = (time.monotonic(), down)
    return down


async def directory_upsert(row: dict) -> None:
    """Keeps the account directory (pg-core) in step with the shard. Never fails the request:
    the coordinator also synchronises it from the shards."""
    try:
        async with core.connection() as conn:
            await conn.execute(
                """INSERT INTO account_directory (iban, user_id, region, currency, status) VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (iban) DO UPDATE SET status = EXCLUDED.status, currency = EXCLUDED.currency,
                       updated_at = now()""",
                (row["iban"], row["user_id"], region_of_iban(row["iban"]), row["currency"], row["status"]))
    except Exception as exc:
        log.warning(f"diretório de contas não atualizado para {row['iban']}: {exc!r}")


async def custody_held(iban: str) -> dict[str, Decimal]:
    """{shard: amount held in custody for iban} over the shards that are up."""
    held = {}
    for region in custody.other_regions(region_of_iban(iban)):
        if await region_down(region):
            continue
        try:
            async with shards.for_region(region).connection(timeout=3) as conn:
                balance = await custody.holdings(conn, iban)
        except Exception as exc:
            log.warning(f"custódia em {region} ilegível: {exc!r}")
            continue
        if balance is not None:
            held[region] = balance
    return held


async def custody_account(iban: str) -> dict:
    """An account whose region is totally down, as it can be used right now: owner, currency
    and status from the directory; balance = what is held in custody in other shards."""
    async with core.connection() as conn:
        d = await (await conn.execute("SELECT * FROM account_directory WHERE iban = %s", (iban,))).fetchone()
    if d is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"região {region_of_iban(iban)} indisponível, tente novamente")
    held = await custody_held(iban)
    return {"iban": iban, "user_id": d["user_id"], "currency": d["currency"], "status": d["status"],
            "balance": sum(held.values(), Decimal(0)), "daily_limit": None, "created_at": None,
            "closed_at": None, "unavailable": True, "held_in": held}


async def eur_value(amount: Decimal, currency: str) -> Decimal:
    """Valor em EUR (os limites institucionais são em EUR)."""
    if currency == "EUR":
        return limits.to_eur(amount, Decimal(1))
    async with core.connection() as conn:
        row = await (await conn.execute(limits.EUR_RATE_SQL, (currency,))).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"sem taxa de câmbio {currency} -> EUR")
    return limits.to_eur(amount, row["rate"])


def check_iban(iban: str) -> None:
    if not is_valid_iban(iban):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "IBAN inválido")


async def load_account(iban: str) -> dict:
    check_iban(iban)
    if await region_down(region_of_iban(iban)):
        return await custody_account(iban)
    try:
        async with read_connection(region_of_iban(iban)) as conn:
            row = await (await conn.execute("SELECT * FROM accounts WHERE iban = %s", (iban,))).fetchone()
    except (psycopg_pool.PoolTimeout, psycopg.OperationalError):
        if await region_down(region_of_iban(iban), fresh=True):   # it has just gone down
            return await custody_account(iban)
        raise
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conta não encontrada")
    return row


def ensure_can_read_account(account: dict, claims: dict) -> None:
    """Cliente: só as suas contas (404 para não revelar que o IBAN existe).
    Staff: precisa da permissão accounts:read:any (operador, auditor, admin)."""
    if has_permission(claims["role"], "accounts:read:any"):
        return
    if has_permission(claims["role"], "accounts:read:own") and str(account["user_id"]) == claims["sub"]:
        return
    if claims["role"] == "cliente":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conta não encontrada")
    raise HTTPException(status.HTTP_403_FORBIDDEN, "sem permissão")


# --- health ----------------------------------------------------------------------

@app.get("/health")
async def health():
    components = {"jwks": {"kids": validator.kids, "last_refresh": validator.last_refresh}}
    for region in REGIONS:
        try:
            async with shards.for_region(region).connection(timeout=3) as conn:
                row = await (await conn.execute(
                    "SELECT host(inet_server_addr()) AS node, pg_is_in_recovery() AS replica")).fetchone()
            components[f"shard_{region}"] = {"ok": True, "node": row["node"]}
        except Exception as exc:
            components[f"shard_{region}"] = {"ok": False, "error": type(exc).__name__}
    ok = bool(validator.kids)  # without keys this instance cannot validate any request
    body = {"status": "ok" if ok else "sem-chaves", "instance": settings.instance_id, "components": components}
    if not ok:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, body)
    return body


# --- client endpoints --------------------------------------------------------------

# GET /me, GET /accounts and the account requests live in accounts.py: a client may hold
# accounts in several regions, so they read every shard.


@app.get("/accounts/{iban}")
async def get_account(iban: str, claims: dict = Depends(current_claims)):
    account = await load_account(iban)
    ensure_can_read_account(account, claims)
    return account_out(account)


@app.get("/accounts/{iban}/movements")
async def movements(iban: str, limit: int = 100, claims: dict = Depends(current_claims)):
    account = await load_account(iban)
    ensure_can_read_account(account, claims)
    limit = min(max(limit, 1), 500)
    if account.get("unavailable"):
        # Region down: the movements made in custody, not yet forwarded to the region.
        rows = []
        for region in account["held_in"]:
            async with shards.for_region(region).connection(timeout=3) as conn:
                rows += [{**r, "via_region": region, "pending_forward": True} for r in await (await conn.execute(
                    """SELECT id, tx_id, type, amount, currency, balance_after, origin, counterparty, created_at
                       FROM custody_movements WHERE target_iban = %s AND forwarded_by IS NULL
                       ORDER BY id DESC LIMIT %s""", (iban, limit))).fetchall()]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
    else:
        async with read_connection(region_of_iban(iban)) as conn:
            rows = await (await conn.execute(
                """SELECT id, tx_id, type, amount, currency, balance_after, origin, via_region, created_at
                   FROM movements WHERE iban = %s ORDER BY created_at DESC, id DESC LIMIT %s""",
                (iban, limit))).fetchall()
    return [{**r, "tx_id": str(r["tx_id"]), "amount": f"{r['amount']:.2f}",
             "balance_after": f"{r['balance_after']:.2f}"} for r in rows[:limit]]


@app.get("/fx-rates")
async def fx_rates(claims: dict = Depends(require_permission("fx:read"))):
    async with core.connection() as conn:
        rows = await (await conn.execute("SELECT base, quote, rate FROM fx_rates ORDER BY base, quote")).fetchall()
    return [{"base": r["base"], "quote": r["quote"], "rate": f"{r['rate']:.8f}"} for r in rows]


# --- operator: local transactions in one shard -------------------------------------

async def cash_operation(iban: str, body: CashOperation, claims: dict, kind: str, request: Request = None) -> dict:
    """Deposit or withdrawal: a normal (local) ACID transaction inside ONE shard."""
    check_iban(iban)
    if await region_down(region_of_iban(iban)):
        return await custody_cash_operation(iban, body, claims, kind, request)
    tx_id = uuid.uuid4()
    error = None
    pool = shards.for_iban(iban)
    try:
        conn = await pool.getconn(timeout=10)
    except psycopg_pool.PoolTimeout:
        # No connection at all: nothing was executed, so it is safe to go to custody instead.
        if await region_down(region_of_iban(iban), fresh=True):
            return await custody_cash_operation(iban, body, claims, kind, request)
        raise
    try:
        async with conn.transaction():
            # Row lock: concurrent operations on the same account wait for each other.
            account = await (await conn.execute(
                "SELECT * FROM accounts WHERE iban = %s FOR UPDATE", (iban,))).fetchone()
            if account is None:
                error = (status.HTTP_404_NOT_FOUND, "conta não encontrada")
            elif account["status"] != "ATIVA":
                error = (status.HTTP_409_CONFLICT, f"conta {account['status']}")
            else:
                delta = body.amount if kind == "DEPOSITO" else -body.amount
                new_balance: Decimal = account["balance"] + delta
                if new_balance < 0:
                    error = (status.HTTP_409_CONFLICT, "saldo insuficiente")
                else:
                    await conn.execute("UPDATE accounts SET balance = %s WHERE iban = %s", (new_balance, iban))
                    await conn.execute(
                        """INSERT INTO movements (iban, tx_id, type, amount, currency, balance_after, origin)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (iban, tx_id, "CREDITO" if kind == "DEPOSITO" else "DEBITO",
                         body.amount, account["currency"], new_balance, kind))
    finally:
        await pool.putconn(conn)
    if error:
        raise HTTPException(*error)
    log.info(f"{kind.lower()} de {body.amount} {account['currency']} em {iban}",
             extra=log_extra(tx_id=str(tx_id), operador=claims["sub"]))
    await record(kind, claims, request, tx_id=str(tx_id), iban=iban, amount=f"{body.amount:.2f}",
                 currency=account["currency"], before={"balance": f"{account['balance']:.2f}"},
                 after={"balance": f"{new_balance:.2f}"})
    await record_report(settings.instance_id, {"type": "cash", "operation": kind, "region": region_of_iban(iban),
                                               "currency": account["currency"], "amount": f"{body.amount:.2f}"},
                        settings.audit_dir)
    return {"tx_id": str(tx_id), "iban": iban, "type": kind, "amount": f"{body.amount:.2f}",
            "currency": account["currency"], "balance": f"{new_balance:.2f}"}


async def custody_cash_operation(iban: str, body: CashOperation, claims: dict, kind: str, request: Request = None) -> dict:
    """Deposit or withdrawal on an account whose region is totally down: done in custody,
    in another shard (a local transaction there). Forwarded when the region is back."""
    region = region_of_iban(iban)
    account = await custody_account(iban)
    if account["status"] != "ATIVA":
        raise HTTPException(status.HTTP_409_CONFLICT, f"conta {account['status']}")
    held = account["held_in"]
    if kind == "DEPOSITO":
        reachable = [r for r in custody.other_regions(region) if not await region_down(r)]
        holder = custody.credit_holder(region, reachable, held)
    else:
        holder = custody.debit_holder(held, body.amount)
    if holder is None:
        raise HTTPException(status.HTTP_409_CONFLICT if kind == "LEVANTAMENTO" else status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"região {region} indisponível" + (" e sem valor retido para esta conta"
                                                               if kind == "LEVANTAMENTO" else ""))
    tx_id = uuid.uuid4()
    async with shards.for_region(holder).connection() as conn:
        async with conn.transaction():
            try:
                new_held = await custody.apply(
                    conn, iban=iban, user_id=account["user_id"], currency=account["currency"],
                    side="CREDITO" if kind == "DEPOSITO" else "DEBITO", amount=body.amount, tx_id=tx_id,
                    origin=kind, counterparty=None)
            except custody.CustodyError as exc:
                raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    total = sum((b for r, b in held.items() if r != holder), Decimal(0)) + new_held
    log.warning(f"região {region} em baixo: {kind.lower()} de {body.amount} {account['currency']} em {iban} "
                f"feito em custódia no shard {holder}", extra=log_extra(tx_id=str(tx_id), operador=claims["sub"]))
    await record(kind, claims, request, tx_id=str(tx_id), iban=iban, amount=f"{body.amount:.2f}",
                 currency=account["currency"], custody_region=holder,
                 before={"held": f"{account['balance']:.2f}"}, after={"held": f"{total:.2f}"})
    await record_report(settings.instance_id, {"type": "cash", "operation": kind, "region": region,
                                               "currency": account["currency"], "amount": f"{body.amount:.2f}"},
                        settings.audit_dir)
    return {"tx_id": str(tx_id), "iban": iban, "type": kind, "amount": f"{body.amount:.2f}",
            "currency": account["currency"], "balance": f"{total:.2f}", "region_unavailable": True,
            "custody_region": holder}


@app.post("/accounts/{iban}/deposit")
async def deposit(iban: str, body: CashOperation, request: Request,
                  claims: dict = Depends(require_permission("accounts:cash"))):
    return await cash_operation(iban, body, claims, "DEPOSITO", request)


@app.post("/accounts/{iban}/withdraw")
async def withdraw(iban: str, body: CashOperation, request: Request,
                   claims: dict = Depends(require_permission("accounts:cash"))):
    return await cash_operation(iban, body, claims, "LEVANTAMENTO", request)


# --- internal (service token) ----------------------------------------------------------

@app.post("/internal/accounts", status_code=status.HTTP_201_CREATED)
async def create_account(body: CreateAccountRequest, claims: dict = Depends(require_permission("accounts:create:internal"))):
    """Called by auth after KYC. Creates the account in the shard of the user's region.
    Idempotent per (user, currency): calling it again returns the same account."""
    async with shards.for_region(body.region).connection() as conn:
        async with conn.transaction():
            # Serialises concurrent calls for the same user (e.g. KYC retried twice).
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (str(body.user_id),))
            existing = await (await conn.execute(
                "SELECT * FROM accounts WHERE user_id = %s AND currency = %s AND status <> 'ENCERRADA'",
                (body.user_id, body.currency))).fetchone()
            if existing:
                return {**account_out(existing), "created": False}
            row = await (await conn.execute(
                """INSERT INTO accounts (iban, user_id, currency)
                   VALUES ('GS-' || %s || '-' || lpad(nextval('iban_seq')::text, 8, '0'), %s, %s)
                   RETURNING *""",
                (body.region, body.user_id, body.currency))).fetchone()
    await directory_upsert(row)
    log.info(f"conta {row['iban']} criada no shard {body.region}", extra=log_extra(user_id=str(body.user_id)))
    await audit.write("CONTA_CRIADA", iban=row["iban"], user_id=str(body.user_id), region=body.region,
                      currency=body.currency, by=claims["sub"])
    return {**account_out(row), "created": True}


# --- transfers (executed by the coordinator) ----------------------------------------------

async def signed_post(path: str, payload: dict) -> httpx.Response:
    """Sends a canonical-JSON body signed with this instance's Ed25519 key."""
    body = canonical_json(payload)
    return await coordinator.post(path, content=body, headers=signed_headers(SIGNING_KEY, settings.instance_id, body))


@app.post("/transfers")
async def create_transfer(body: TransferRequest,
                          request: Request,
                          idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100),
                          claims: dict = Depends(require_permission("transfers:create:own"))):
    if not (is_valid_iban(body.from_iban) and is_valid_iban(body.to_iban)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "IBAN inválido")
    if body.from_iban == body.to_iban:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "origem e destino iguais")
    conf = await admin.current_settings()
    source = await load_account(body.from_iban)
    if str(source["user_id"]) != claims["sub"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conta de origem não encontrada")  # not yours
    # The maximum per transfer is in EUR, converted to the source account currency
    # (the coordinator checks it again, together with the daily limit per client).
    if problem := limits.max_problem(await eur_value(body.amount, source["currency"]), conf["max_transfer_amount"]):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    await load_account(body.to_iban)  # 404 if the destination does not exist

    tx_id = transfer_tx_id(claims["sub"], idempotency_key)
    tx_id_var.set(str(tx_id))
    payload = {
        "tx_id": str(tx_id), "idempotency_key": idempotency_key, "user_id": claims["sub"],
        "from_iban": body.from_iban, "to_iban": body.to_iban, "amount": f"{body.amount:.2f}",
        "ts": datetime.now(timezone.utc).isoformat(), "requested_by": settings.instance_id,
        "initiated_by": claims["sub"], "initiated_role": claims["role"],
    }
    try:
        response = await signed_post("/tx", payload)
    except httpx.HTTPError as exc:
        log.warning(f"coordenador indisponível: {exc!r}")
        # The client knows its tx_id and can safely retry with the same Idempotency-Key.
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={
            "detail": "coordenador indisponível: repita o pedido com a mesma Idempotency-Key",
            "tx_id": str(tx_id)})
    return JSONResponse(response.json(), status_code=response.status_code)


@app.get("/transfers/{tx_id}")
async def get_transfer(tx_id: uuid.UUID, claims: dict = Depends(require_permission("transfers:read:any", "transfers:read:own"))):
    async with core.connection() as conn:
        tx = await (await conn.execute("SELECT * FROM transactions WHERE tx_id = %s", (tx_id,))).fetchone()
        if tx is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "transação não encontrada")
        if not has_permission(claims["role"], "transfers:read:any") and str(tx["user_id"]) != claims["sub"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "transação não encontrada")
        events = await (await conn.execute(
            "SELECT event, detail, at FROM tx_events WHERE tx_id = %s ORDER BY id", (tx_id,))).fetchall()
    tx.pop("request_signature", None)
    # Money as decimal strings ("21150.00"), never floats.
    tx = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in tx.items()}
    return {**tx, "events": events}


# --- admin ------------------------------------------------------------------------------

@app.post("/admin/chaos")
async def set_chaos(body: ChaosRequest, request: Request, claims: dict = Depends(require_permission("system:chaos"))):
    mode = {k: v for k, v in body.model_dump().items() if v is not None}
    await record("SIMULACAO_FALHAS", claims, request, after=mode)
    try:
        response = await signed_post("/admin/chaos", {"mode": mode, "by": claims["sub"],
                                                      "ts": datetime.now(timezone.utc).isoformat()})
    except httpx.HTTPError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "coordenador indisponível")
    return JSONResponse(response.json(), status_code=response.status_code)


@app.get("/admin/consistency")
async def consistency(claims: dict = Depends(require_permission("audit:read"))):
    """Checks the 2PC guarantees across ALL shards:
    - every CONFIRMADA transfer has exactly 1 DEBITO (origin shard) and 1 CREDITO (destination shard)
    - every ABORTADA transfer has no movement at all
    - no transfer movement exists without a CONFIRMADA transaction (orphan)
    - no prepared transaction is left hanging in the shards
    """
    async with core.connection() as conn:
        txs = await (await conn.execute(
            "SELECT tx_id, state, kind, from_iban, to_iban, from_region, to_region, amount, converted_amount "
            "FROM transactions")).fetchall()
    movements: dict[str, list] = {}
    prepared: dict[str, list] = {}
    for region in REGIONS:
        async with shards.for_region(region).connection() as conn:
            for m in await (await conn.execute(
                    "SELECT tx_id, iban, type, amount FROM movements WHERE origin = 'TRANSFERENCIA'")).fetchall():
                movements.setdefault(str(m["tx_id"]), []).append({**m, "region": region})
            prepared[region] = [r["gid"] for r in await (await conn.execute(
                "SELECT gid FROM pg_prepared_xacts WHERE database = current_database()")).fetchall()]
            # Legs kept in custody (region of the account was down) and not yet forwarded:
            # they count as being in the account's region. Once forwarded they are in its
            # movements table (replayed), so they are read above instead.
            for m in await (await conn.execute(
                    """SELECT m.tx_id, m.target_iban AS iban, m.type, m.amount, c.target_region
                       FROM custody_movements m JOIN custody_accounts c USING (target_iban)
                       WHERE m.origin = 'TRANSFERENCIA' AND m.forwarded_by IS NULL""")).fetchall():
                movements.setdefault(str(m["tx_id"]), []).append({**m, "region": m["target_region"]})

    problems, in_progress = [], []
    by_id = {str(t["tx_id"]): t for t in txs}
    for tx_id, tx in by_id.items():
        moves = movements.get(tx_id, [])
        if tx["state"] == "CONFIRMADA":
            debit = [m for m in moves if m["type"] == "DEBITO" and m["iban"] == tx["from_iban"]
                     and m["region"] == tx["from_region"] and m["amount"] == tx["amount"]]
            credit = [m for m in moves if m["type"] == "CREDITO" and m["iban"] == tx["to_iban"]
                      and m["region"] == tx["to_region"] and m["amount"] == tx["converted_amount"]]
            if len(debit) != 1 or len(credit) != 1 or len(moves) != 2:
                problems.append({"tx_id": tx_id, "problem": "CONFIRMADA sem exatamente 1 débito + 1 crédito",
                                 "movements": len(moves)})
        elif tx["state"] == "ABORTADA":
            if moves:
                problems.append({"tx_id": tx_id, "problem": "ABORTADA com movimentos", "movements": len(moves)})
        else:
            in_progress.append({"tx_id": tx_id, "state": tx["state"]})
    for tx_id in movements.keys() - by_id.keys():
        problems.append({"tx_id": tx_id, "problem": "movimento órfão (sem transação no log)"})
    hanging = {r: g for r, g in prepared.items() if g}
    if hanging and not in_progress:
        problems.append({"problem": "transações preparadas penduradas nos shards", "prepared": hanging})

    result = {
        "ok": not problems, "checked_transactions": len(txs),
        "confirmed": sum(t["state"] == "CONFIRMADA" for t in txs),
        "aborted": sum(t["state"] == "ABORTADA" for t in txs),
        "in_progress": in_progress, "prepared_xacts": prepared, "problems": problems,
    }
    await audit.write("VERIFICACAO_CONSISTENCIA", ok=result["ok"], problems=len(problems), by=claims["sub"])
    return result


def today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


@app.get("/admin/audit")
async def audit_check(date: str = Query(default_factory=today, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                      claims: dict = Depends(require_permission("audit:read"))):
    """Reads the audit logs of every node from the NFS and validates each hash chain."""
    def check() -> dict:
        folder = os.path.join(settings.audit_dir, date)
        if not os.path.isdir(folder):
            return {}
        out = {}
        for name in sorted(os.listdir(folder)):
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                lines = [l for l in f.read().splitlines() if l.strip()]
            ok, bad_line, reason = verify_chain(lines)
            out[name] = {"lines": len(lines), "ok": ok, "first_bad_line": bad_line, "reason": reason}
            if bad_line:
                out[name]["bad_content"] = lines[bad_line - 1][:300]
        return out

    files = await asyncio.to_thread(check)
    if not files:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"sem auditoria para {date}")
    return {"date": date, "ok": all(f["ok"] for f in files.values()), "files": files,
            "checked_by": settings.instance_id}


@app.get("/admin/reports")
async def daily_report(date: str = Query(default_factory=today, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                       claims: dict = Depends(require_permission("reports:read"))):
    report = await asyncio.to_thread(read_report, settings.audit_dir, date)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"sem relatório para {date}")
    return report


SERVICES_HEALTH = {
    "auth": "https://auth.global.local:8010/health",
    "coordinator": "https://coordinator.global.local:8020/health",
    "legacy-bank": "https://legacy-bank.global.local:9443/health",
    "api-1": "https://api-1.global.local:8000/health",
    "api-2": "https://api-2.global.local:8000/health",
}
DB_NODES = {"pg-core": "coordinator"} | {
    node.split(".")[0]: "bank" for r in REGIONS for node in SHARD_NODES[r]
}


@app.get("/admin/status")
async def cluster_status(claims: dict = Depends(require_permission("system:status"))):
    """State of every node: services (HTTPS /health), databases (primary/replica,
    pending prepared transactions) and the NFS."""
    async def service(name: str, url: str):
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(verify=ssl.create_default_context(cafile=settings.ca_file), timeout=3) as c:
                r = await c.get(url)
            return name, {"up": r.status_code < 500, "http": r.status_code, "ms": round((time.perf_counter() - start) * 1000)}
        except Exception as exc:
            return name, {"up": False, "error": type(exc).__name__}

    async def database(node: str, dbname: str):
        conninfo = (f"host={node}.global.local dbname={dbname} user={settings.db_user} password={settings.db_password} "
                    f"sslmode=verify-full sslrootcert={settings.ca_file} connect_timeout=2")
        try:
            async with await psycopg.AsyncConnection.connect(conninfo) as conn:
                row = await (await conn.execute(
                    "SELECT pg_is_in_recovery(), (SELECT count(*) FROM pg_prepared_xacts), "
                    "(SELECT count(*) FROM pg_stat_replication), current_setting('ssl')")).fetchone()
            return node, {"up": True, "role": "réplica" if row[0] else "primário", "prepared_xacts": row[1],
                          "replicas_streaming": row[2], "ssl": row[3]}
        except Exception as exc:
            return node, {"up": False, "error": type(exc).__name__}

    results = await asyncio.gather(*(service(n, u) for n, u in SERVICES_HEALTH.items()),
                                   *(database(n, d) for n, d in DB_NODES.items()))
    services = dict(results[:len(SERVICES_HEALTH)])
    databases = dict(results[len(SERVICES_HEALTH):])
    services[settings.instance_id] = {"up": True, "self": True}
    try:
        days = sorted(d for d in os.listdir(settings.audit_dir) if d[:2] == "20")
        nfs = {"up": True, "mount": settings.audit_dir, "days": days[-5:]}
    except OSError as exc:
        nfs = {"up": False, "error": repr(exc)}
    return {"served_by": settings.instance_id, "services": services, "databases": databases, "nfs": nfs,
            "all_up": all(v["up"] for v in [*services.values(), *databases.values(), nfs])}


# --- Administração, operações e auditoria (módulo admin.py) ----------------------------------
from . import accounts, admin  # noqa: E402  (precisam das dependências definidas acima)

app.include_router(admin.router)
app.include_router(accounts.router)
