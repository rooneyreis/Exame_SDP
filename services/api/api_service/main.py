"""Public API (two instances, api-1 and api-2, behind nginx).

- Validates JWTs LOCALLY with the auth public key (JWKS kept in cache): if auth is
  down, tokens already issued keep working.
- Routes every account to its shard by the IBAN prefix / the user's region (common/db.py).
- Returns X-Served-By so the load balancing is visible.
(Transfers and admin endpoints are added in Phases 4 and 6.)
"""
import asyncio
import ssl
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse

from common.audit import AuditLog
from common.crypto import canonical_json, load_ed25519_private, signed_headers
from common.db import REGIONS, ShardRouter, is_valid_iban, make_pool, region_of_iban, shard_conninfo
from common.jwt_auth import TokenValidator, auth_dependencies
from common.logging import add_request_logging, log_extra, setup_logging, tx_id_var
from common.transfers import transfer_tx_id

from .config import settings
from .schemas import CashOperation, ChaosRequest, CreateAccountRequest, TransferRequest

log = setup_logging(settings.instance_id)
audit = AuditLog(settings.instance_id, settings.audit_dir)

validator = TokenValidator(jwks_url=settings.jwks_url, ca_file=settings.ca_file,
                           refresh_seconds=settings.jwks_refresh_seconds)
current_claims, require_role = auth_dependencies(validator)

shards = ShardRouter({r: shard_conninfo(r, settings.db_user, settings.db_password, settings.ca_file)
                      for r in REGIONS})
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


@app.middleware("http")
async def served_by(request, call_next):
    response = await call_next(request)
    response.headers["X-Served-By"] = settings.instance_id
    return response


# --- helpers -------------------------------------------------------------------

def account_out(row: dict) -> dict:
    return {
        "iban": row["iban"], "user_id": str(row["user_id"]), "region": region_of_iban(row["iban"]),
        "currency": row["currency"], "balance": f"{row['balance']:.2f}", "status": row["status"],
        "daily_limit": f"{row['daily_limit']:.2f}", "created_at": row["created_at"],
    }


def check_iban(iban: str) -> None:
    if not is_valid_iban(iban):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "IBAN inválido")


async def load_account(iban: str) -> dict:
    check_iban(iban)
    async with shards.for_iban(iban).connection() as conn:
        row = await (await conn.execute("SELECT * FROM accounts WHERE iban = %s", (iban,))).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conta não encontrada")
    return row


def ensure_owner_or_role(account: dict, claims: dict, *staff_roles: str) -> None:
    """A client only sees its own accounts; staff roles listed here see any account."""
    if claims["role"] == "cliente":
        if str(account["user_id"]) != claims["sub"]:
            # 404 instead of 403: does not reveal that the IBAN exists
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conta não encontrada")
    elif claims["role"] not in staff_roles:
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

@app.get("/me")
async def me(claims: dict = Depends(current_claims)):
    accounts = []
    if claims["role"] == "cliente":
        async with shards.for_region(claims["region"]).connection() as conn:
            rows = await (await conn.execute(
                "SELECT * FROM accounts WHERE user_id = %s ORDER BY iban", (claims["sub"],))).fetchall()
        accounts = [account_out(r) for r in rows]
    return {"user_id": claims["sub"], "role": claims["role"], "region": claims["region"],
            "token_expires_at": claims["exp"], "accounts": accounts}


@app.get("/accounts")
async def my_accounts(claims: dict = Depends(require_role("cliente"))):
    # The user's region (JWT claim) says which shard holds their accounts.
    async with shards.for_region(claims["region"]).connection() as conn:
        rows = await (await conn.execute(
            "SELECT * FROM accounts WHERE user_id = %s ORDER BY iban", (claims["sub"],))).fetchall()
    return [account_out(r) for r in rows]


@app.get("/accounts/{iban}")
async def get_account(iban: str, claims: dict = Depends(current_claims)):
    account = await load_account(iban)
    ensure_owner_or_role(account, claims, "operador")
    return account_out(account)


@app.get("/accounts/{iban}/movements")
async def movements(iban: str, limit: int = 100, claims: dict = Depends(current_claims)):
    account = await load_account(iban)
    ensure_owner_or_role(account, claims, "operador", "auditor")
    async with shards.for_iban(iban).connection() as conn:
        rows = await (await conn.execute(
            """SELECT id, tx_id, type, amount, currency, balance_after, origin, created_at
               FROM movements WHERE iban = %s ORDER BY id DESC LIMIT %s""",
            (iban, min(max(limit, 1), 500)))).fetchall()
    return [{**r, "tx_id": str(r["tx_id"]), "amount": f"{r['amount']:.2f}",
             "balance_after": f"{r['balance_after']:.2f}"} for r in rows]


@app.get("/fx-rates")
async def fx_rates(claims: dict = Depends(current_claims)):
    async with core.connection() as conn:
        rows = await (await conn.execute("SELECT base, quote, rate FROM fx_rates ORDER BY base, quote")).fetchall()
    return [{"base": r["base"], "quote": r["quote"], "rate": f"{r['rate']:.8f}"} for r in rows]


# --- operator: local transactions in one shard -------------------------------------

async def cash_operation(iban: str, body: CashOperation, claims: dict, kind: str) -> dict:
    """Deposit or withdrawal: a normal (local) ACID transaction inside ONE shard."""
    check_iban(iban)
    tx_id = uuid.uuid4()
    error = None
    async with shards.for_iban(iban).connection() as conn:
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
    if error:
        raise HTTPException(*error)
    log.info(f"{kind.lower()} de {body.amount} {account['currency']} em {iban}",
             extra=log_extra(tx_id=str(tx_id), operador=claims["sub"]))
    await audit.write(kind, tx_id=str(tx_id), iban=iban, amount=f"{body.amount:.2f}",
                      currency=account["currency"], balance_after=f"{new_balance:.2f}", operador=claims["sub"])
    return {"tx_id": str(tx_id), "iban": iban, "type": kind, "amount": f"{body.amount:.2f}",
            "currency": account["currency"], "balance": f"{new_balance:.2f}"}


@app.post("/accounts/{iban}/deposit")
async def deposit(iban: str, body: CashOperation, claims: dict = Depends(require_role("operador"))):
    return await cash_operation(iban, body, claims, "DEPOSITO")


@app.post("/accounts/{iban}/withdraw")
async def withdraw(iban: str, body: CashOperation, claims: dict = Depends(require_role("operador"))):
    return await cash_operation(iban, body, claims, "LEVANTAMENTO")


# --- internal (service token) ----------------------------------------------------------

@app.post("/internal/accounts", status_code=status.HTTP_201_CREATED)
async def create_account(body: CreateAccountRequest, claims: dict = Depends(require_role("service"))):
    """Called by auth after KYC. Creates the account in the shard of the user's region.
    Idempotent per (user, currency): calling it again returns the same account."""
    async with shards.for_region(body.region).connection() as conn:
        async with conn.transaction():
            # Serialises concurrent calls for the same user (e.g. KYC retried twice).
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (str(body.user_id),))
            existing = await (await conn.execute(
                "SELECT * FROM accounts WHERE user_id = %s AND currency = %s", (body.user_id, body.currency))).fetchone()
            if existing:
                return {**account_out(existing), "created": False}
            row = await (await conn.execute(
                """INSERT INTO accounts (iban, user_id, currency)
                   VALUES ('GS-' || %s || '-' || lpad(nextval('iban_seq')::text, 8, '0'), %s, %s)
                   RETURNING *""",
                (body.region, body.user_id, body.currency))).fetchone()
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
                          idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100),
                          claims: dict = Depends(require_role("cliente"))):
    if not (is_valid_iban(body.from_iban) and is_valid_iban(body.to_iban)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "IBAN inválido")
    if body.from_iban == body.to_iban:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "origem e destino iguais")
    source = await load_account(body.from_iban)
    if str(source["user_id"]) != claims["sub"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conta de origem não encontrada")  # not yours
    await load_account(body.to_iban)  # 404 if the destination does not exist

    tx_id = transfer_tx_id(claims["sub"], idempotency_key)
    tx_id_var.set(str(tx_id))
    payload = {
        "tx_id": str(tx_id), "idempotency_key": idempotency_key, "user_id": claims["sub"],
        "from_iban": body.from_iban, "to_iban": body.to_iban, "amount": f"{body.amount:.2f}",
        "ts": datetime.now(timezone.utc).isoformat(), "requested_by": settings.instance_id,
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
async def get_transfer(tx_id: uuid.UUID, claims: dict = Depends(current_claims)):
    async with core.connection() as conn:
        tx = await (await conn.execute("SELECT * FROM transactions WHERE tx_id = %s", (tx_id,))).fetchone()
        if tx is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "transação não encontrada")
        if claims["role"] == "cliente" and str(tx["user_id"]) != claims["sub"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "transação não encontrada")
        if claims["role"] not in ("cliente", "operador", "auditor", "admin"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "sem permissão")
        events = await (await conn.execute(
            "SELECT event, detail, at FROM tx_events WHERE tx_id = %s ORDER BY id", (tx_id,))).fetchall()
    tx.pop("request_signature", None)
    # Money as decimal strings ("21150.00"), never floats.
    tx = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in tx.items()}
    return {**tx, "events": events}


# --- admin ------------------------------------------------------------------------------

@app.post("/admin/chaos")
async def set_chaos(body: ChaosRequest, claims: dict = Depends(require_role("admin"))):
    mode = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        response = await signed_post("/admin/chaos", {"mode": mode, "by": claims["sub"],
                                                      "ts": datetime.now(timezone.utc).isoformat()})
    except httpx.HTTPError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "coordenador indisponível")
    return JSONResponse(response.json(), status_code=response.status_code)


@app.get("/admin/consistency")
async def consistency(claims: dict = Depends(require_role("auditor", "admin"))):
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
