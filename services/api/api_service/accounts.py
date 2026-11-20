"""Várias contas por cliente, em regiões e moedas diferentes.

- O cliente pede a abertura (região + moeda) ou o encerramento de uma conta; um operador
  aprova ou rejeita (com motivo). O operador também pode abrir uma conta ao balcão.
- A conta é criada no shard da região ESCOLHIDA (não na região de registo do cliente):
  o routing continua a ser só pelo prefixo do IBAN (common/db.py).
- Regras: no máximo N contas ativas por cliente (settings.max_accounts_per_client), uma só
  conta ativa por região+moeda, cliente ATIVO. A criação é idempotente.
- Encerrar só com saldo 0 e sem transações em curso: a conta fica ENCERRADA, nunca é apagada.
- Tudo fica no registo de auditoria encadeado (record -> NFS).
"""
import asyncio
import ssl
import uuid
from decimal import Decimal

import httpx
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from common import limits
from common.db import REGIONS, region_of_iban

from .main import (account_out, audit, core, current_claims, load_account, log, read_connection, record,
                   require_permission, settings, shards)
from .schemas import AccountRequestIn, Decision, DirectAccountIn

router = APIRouter()

AUTH_URL = settings.jwks_url.split("/.well-known")[0]
auth_client = httpx.AsyncClient(base_url=AUTH_URL, verify=ssl.create_default_context(cafile=settings.ca_file),
                                timeout=httpx.Timeout(8, connect=3))

# Leitura de um shard para a listagem do cliente: se a região não responder neste tempo
# (primário E réplica em baixo), a listagem devolve as outras e indica a que falta.
SHARD_READ_TIMEOUT = 6


def jsonable(row: dict) -> dict:
    return {k: (str(v) if isinstance(v, (uuid.UUID, Decimal)) else v) for k, v in row.items()}


# --- leitura: contas do cliente em TODOS os shards ------------------------------------------

async def client_accounts(user_id: str) -> tuple[list[dict], list[str]]:
    """(contas de todas as regiões, regiões indisponíveis). Uma região em baixo não faz
    falhar as outras: o cliente continua a ver (e a usar) as contas que estão acessíveis."""
    async def fetch(region: str):
        async with read_connection(region) as conn:
            return await (await conn.execute(
                "SELECT * FROM accounts WHERE user_id = %s ORDER BY created_at, iban", (user_id,))).fetchall()

    async def guarded(region: str):
        try:
            return region, await asyncio.wait_for(fetch(region), SHARD_READ_TIMEOUT)
        except Exception as exc:          # timeout, pool timeout, OperationalError...
            log.warning(f"contas do cliente: região {region} indisponível ({type(exc).__name__})")
            return region, None

    results = await asyncio.gather(*(guarded(r) for r in REGIONS))
    rows = [a for _, part in results if part for a in part]
    unavailable = [r for r, part in results if part is None]
    return rows, unavailable


def active(rows: list[dict]) -> list[dict]:
    return [a for a in rows if a["status"] != "ENCERRADA"]


@router.get("/accounts")
async def my_accounts(response: Response, claims: dict = Depends(require_permission("accounts:read:own"))):
    rows, unavailable = await client_accounts(claims["sub"])
    if unavailable:
        response.headers["X-Unavailable-Regions"] = ",".join(unavailable)
    return [account_out(r) for r in rows]


@router.get("/me")
async def me(response: Response, claims: dict = Depends(current_claims)):
    accounts, unavailable = [], []
    if claims["role"] == "cliente":
        rows, unavailable = await client_accounts(claims["sub"])
        accounts = [account_out(r) for r in rows]
        if unavailable:
            response.headers["X-Unavailable-Regions"] = ",".join(unavailable)
    return {"user_id": claims["sub"], "role": claims["role"], "region": claims["region"],
            "token_expires_at": claims["exp"], "accounts": accounts, "unavailable_regions": unavailable}


@router.get("/me/limits")
async def my_limits(claims: dict = Depends(require_permission("accounts:read:own"))):
    """Quanto o cliente já enviou hoje (todas as contas, em EUR) e quanto ainda pode enviar."""
    conf = await current_settings()
    async with core.connection() as conn:
        sent = await (await conn.execute(limits.SENT_TODAY_SQL, (claims["sub"],))).fetchone()
        rates = {r["base"]: r["rate"] for r in await (await conn.execute(
            "SELECT base, rate FROM fx_rates WHERE quote = 'EUR'")).fetchall()}
        back = {r["quote"]: r["rate"] for r in await (await conn.execute(
            "SELECT quote, rate FROM fx_rates WHERE base = 'EUR'")).fetchall()}
    rows, unavailable = await client_accounts(claims["sub"])
    remaining = max(conf["daily_limit_eur"] - sent["total"], Decimal(0))
    currencies = sorted({a["currency"] for a in active(rows)} | {"EUR"})
    return {
        "daily_limit_eur": f"{conf['daily_limit_eur']:.2f}",
        "sent_today_eur": f"{sent['total']:.2f}",
        "remaining_eur": f"{remaining:.2f}",
        "transfers_today": sent["n"],
        "max_transfer_eur": f"{conf['max_transfer_amount']:.2f}",
        # o mesmo limite expresso na moeda de cada conta do cliente (ao câmbio do dia)
        "remaining_by_currency": {c: f"{limits.to_eur(remaining, back.get(c, Decimal(1)) if c != 'EUR' else Decimal(1)):.2f}"
                                  for c in currencies if c == "EUR" or c in back},
        "max_accounts": int(conf["max_accounts_per_client"]),
        "active_accounts": len(active(rows)),
        "unavailable_regions": unavailable,
        "note": "transferências entre contas do próprio cliente não contam para o limite diário",
    }


async def current_settings() -> dict:
    async with core.connection() as conn:
        rows = await (await conn.execute("SELECT key, value FROM settings")).fetchall()
    return {**limits.DEFAULTS, **{r["key"]: r["value"] for r in rows}}


# --- criação de contas (idempotente) -----------------------------------------------------------

async def open_account_in_shard(user_id: str, region: str, currency: str) -> tuple[dict, bool]:
    """Cria a conta no shard da REGIÃO ESCOLHIDA. Idempotente por (cliente, região, moeda):
    se já existir uma conta ativa igual, devolve-a (created=False) em vez de criar outra.
    O advisory lock serializa chamadas concorrentes para o mesmo cliente nesse shard."""
    daily = Decimal("2500000") if currency == "MZN" else Decimal("50000")
    async with shards.for_region(region).connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (str(user_id),))
            existing = await (await conn.execute(
                "SELECT * FROM accounts WHERE user_id = %s AND currency = %s AND status <> 'ENCERRADA'",
                (user_id, currency))).fetchone()
            if existing:
                return existing, False
            row = await (await conn.execute(
                """INSERT INTO accounts (iban, user_id, currency, daily_limit)
                   VALUES ('GS-' || %s || '-' || lpad(nextval('iban_seq')::text, 8, '0'), %s, %s, %s)
                   RETURNING *""", (region, user_id, currency, daily))).fetchone()
    log.info(f"conta {row['iban']} criada no shard {region}")
    await audit.write("CONTA_CRIADA", iban=row["iban"], user_id=str(user_id), region=region, currency=currency)
    return row, True


async def client_status(user_id: str, request: Request) -> dict:
    """Confirma no serviço auth que o titular existe, é cliente e está ATIVO.
    Usa o token de quem decide (operador): o auth aplica o seu próprio controlo de acesso."""
    try:
        r = await auth_client.get("/admin/users", params={"role": "cliente"},
                                  headers={"Authorization": request.headers.get("authorization", "")})
    except httpx.HTTPError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "serviço de autenticação indisponível")
    if r.status_code != 200:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"não foi possível validar o cliente ({r.status_code})")
    user = next((u for u in r.json() if u["id"] == str(user_id)), None)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cliente não encontrado")
    if user["status"] != "ATIVA":
        raise HTTPException(status.HTTP_409_CONFLICT, f"o cliente não está ativo ({user['status']})")
    return user


async def checked_open(user_id: str, region: str, currency: str, *, allow_existing: bool) -> tuple[dict, bool]:
    """Aplica as regras (máximo de contas, região+moeda única) e cria a conta.
    O lock por cliente no pg-core serializa aberturas concorrentes em regiões diferentes,
    para que nunca se ultrapasse o máximo."""
    conf = await current_settings()
    async with core.connection() as lock_conn:
        async with lock_conn.transaction():
            await lock_conn.execute("SELECT pg_advisory_xact_lock(hashtext('accounts:' || %s))", (str(user_id),))
            rows, unavailable = await client_accounts(str(user_id))
            if unavailable:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                    f"não é possível validar as regras com as regiões {', '.join(unavailable)} indisponíveis")
            current = active(rows)
            same = [a for a in current if region_of_iban(a["iban"]) == region and a["currency"] == currency]
            if same:
                if allow_existing:      # repetição (aprovar duas vezes, falha de rede): devolve a mesma conta
                    return same[0], False
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"o cliente já tem uma conta {currency} na região {region} ({same[0]['iban']})")
            if len(current) >= int(conf["max_accounts_per_client"]):
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"máximo de {int(conf['max_accounts_per_client'])} contas ativas por cliente atingido")
            return await open_account_in_shard(str(user_id), region, currency)


# --- pedidos do cliente ------------------------------------------------------------------------

async def load_request(request_id) -> dict:
    async with core.connection() as conn:
        row = await (await conn.execute("SELECT * FROM account_requests WHERE id = %s", (request_id,))).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pedido não encontrado")
    return row


@router.post("/account-requests", status_code=status.HTTP_201_CREATED)
async def request_account(body: AccountRequestIn, request: Request,
                          claims: dict = Depends(require_permission("accounts:request:own"))):
    """O cliente pede uma conta nova (região + moeda). Fica PENDENTE até um operador decidir."""
    conf = await current_settings()
    rows, unavailable = await client_accounts(claims["sub"])
    if unavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"regiões indisponíveis: {', '.join(unavailable)}")
    current = active(rows)
    if any(region_of_iban(a["iban"]) == body.region and a["currency"] == body.currency for a in current):
        raise HTTPException(status.HTTP_409_CONFLICT, f"já tem uma conta {body.currency} na região {body.region}")
    async with core.connection() as conn:
        pending = (await (await conn.execute(
            "SELECT count(*) AS n FROM account_requests WHERE user_id = %s AND kind = 'ABERTURA' AND status = 'PENDENTE'",
            (claims["sub"],))).fetchone())["n"]
    if len(current) + pending >= int(conf["max_accounts_per_client"]):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"máximo de {int(conf['max_accounts_per_client'])} contas ativas por cliente (incluindo pedidos pendentes)")
    rid = uuid.uuid4()
    try:
        async with core.connection() as conn:
            await conn.execute(
                """INSERT INTO account_requests (id, user_id, kind, region, currency, status, created_by, created_by_role)
                   VALUES (%s, %s, 'ABERTURA', %s, %s, 'PENDENTE', %s, %s)""",
                (rid, claims["sub"], body.region, body.currency, claims["sub"], claims["role"]))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "já existe um pedido pendente para esta região e moeda")
    await record("CONTA_PEDIDO_ABERTURA", claims, request, request_id=str(rid),
                 after={"region": body.region, "currency": body.currency})
    return jsonable(await load_request(rid))


@router.post("/accounts/{iban}/closure", status_code=status.HTTP_201_CREATED)
async def request_closure(iban: str, request: Request, claims: dict = Depends(require_permission("accounts:request:own"))):
    """O cliente pede o encerramento; o operador confirma. Só com saldo 0."""
    account = await load_account(iban)
    if str(account["user_id"]) != claims["sub"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conta não encontrada")
    if account["status"] == "ENCERRADA":
        raise HTTPException(status.HTTP_409_CONFLICT, "a conta já está encerrada")
    if account["balance"] != 0:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"só é possível encerrar com saldo 0 (saldo atual {account['balance']:.2f} {account['currency']})")
    rid = uuid.uuid4()
    try:
        async with core.connection() as conn:
            await conn.execute(
                """INSERT INTO account_requests (id, user_id, kind, region, currency, iban, status, created_by, created_by_role)
                   VALUES (%s, %s, 'ENCERRAMENTO', %s, %s, %s, 'PENDENTE', %s, %s)""",
                (rid, claims["sub"], region_of_iban(iban), account["currency"], iban, claims["sub"], claims["role"]))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "já existe um pedido de encerramento pendente para esta conta")
    await record("CONTA_PEDIDO_ENCERRAMENTO", claims, request, request_id=str(rid), iban=iban)
    return jsonable(await load_request(rid))


@router.get("/account-requests")
async def my_requests(claims: dict = Depends(require_permission("accounts:request:own"))):
    async with core.connection() as conn:
        rows = await (await conn.execute(
            "SELECT * FROM account_requests WHERE user_id = %s ORDER BY created_at DESC LIMIT 50",
            (claims["sub"],))).fetchall()
    return [jsonable(r) for r in rows]


# --- operador: decidir pedidos e abrir contas ao balcão ------------------------------------------

@router.get("/admin/account-requests")
async def list_account_requests(status_filter: str | None = Query(None, alias="status"), kind: str | None = None,
                                claims: dict = Depends(require_permission("account_requests:read"))):
    where, args = [], []
    if status_filter:
        where.append("status = %s"); args.append(status_filter)
    if kind:
        where.append("kind = %s"); args.append(kind)
    async with core.connection() as conn:
        rows = await (await conn.execute(
            f"SELECT * FROM account_requests {'WHERE ' + ' AND '.join(where) if where else ''} "
            "ORDER BY created_at DESC LIMIT 200", args)).fetchall()
    return [jsonable(r) for r in rows]


async def close_account(iban: str) -> dict:
    """Encerramento: saldo 0 e nenhuma transação em curso (log do coordenador + locks no shard)."""
    async with core.connection() as conn:
        busy = (await (await conn.execute(
            """SELECT count(*) AS n FROM transactions
               WHERE (from_iban = %s OR to_iban = %s) AND state IN ('INICIADA','PREPARANDO','DECISAO_COMMIT')""",
            (iban, iban))).fetchone())["n"]
    if busy:
        raise HTTPException(status.HTTP_409_CONFLICT, "a conta tem transações em curso")
    try:
        async with shards.for_iban(iban).connection() as conn:
            async with conn.transaction():
                # Uma transação preparada (2PC) mantém o lock da linha: não esperamos por ela.
                await conn.execute("SET LOCAL lock_timeout = '2s'")
                account = await (await conn.execute("SELECT * FROM accounts WHERE iban = %s FOR UPDATE", (iban,))).fetchone()
                if account is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "conta não encontrada")
                if account["status"] == "ENCERRADA":
                    return account
                if account["balance"] != 0:
                    raise HTTPException(status.HTTP_409_CONFLICT,
                                        f"só é possível encerrar com saldo 0 (saldo {account['balance']:.2f} {account['currency']})")
                return await (await conn.execute(
                    "UPDATE accounts SET status = 'ENCERRADA', closed_at = now() WHERE iban = %s RETURNING *",
                    (iban,))).fetchone()
    except psycopg.errors.LockNotAvailable:
        raise HTTPException(status.HTTP_409_CONFLICT, "a conta tem uma transação em curso (bloqueada)")


@router.post("/admin/account-requests/{request_id}/approve")
async def approve_account_request(request_id: uuid.UUID, request: Request,
                                  claims: dict = Depends(require_permission("account_requests:decide"))):
    req = await load_request(request_id)
    if req["status"] != "PENDENTE":
        raise HTTPException(status.HTTP_409_CONFLICT, f"pedido já decidido ({req['status']})")
    await client_status(str(req["user_id"]), request)
    if req["kind"] == "ABERTURA":
        account, created = await checked_open(str(req["user_id"]), req["region"], req["currency"], allow_existing=True)
        action = "CONTA_ABERTURA_APROVADA"
    else:
        account, created = await close_account(req["iban"]), False
        action = "CONTA_ENCERRADA"
    async with core.connection() as conn:
        # Atómico: só um operador decide; aprovar duas vezes não repete nada.
        await conn.execute(
            """UPDATE account_requests SET status = 'APROVADO', iban = %s, decided_by = %s, decided_at = now()
               WHERE id = %s AND status = 'PENDENTE'""", (account["iban"], claims["sub"], request_id))
    await record(action, claims, request, request_id=str(request_id), iban=account["iban"],
                 user_id=str(req["user_id"]), region=req["region"], currency=req["currency"],
                 after={"status": account["status"], "created": created})
    return {"request": jsonable(await load_request(request_id)), "account": {**account_out(account), "created": created}}


@router.post("/admin/account-requests/{request_id}/reject")
async def reject_account_request(request_id: uuid.UUID, body: Decision, request: Request,
                                 claims: dict = Depends(require_permission("account_requests:decide"))):
    if not body.reason or len(body.reason.strip()) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "indique o motivo da rejeição")
    async with core.connection() as conn:
        row = await (await conn.execute(
            """UPDATE account_requests SET status = 'REJEITADO', decided_by = %s, decided_at = now(), decision_reason = %s
               WHERE id = %s AND status = 'PENDENTE' RETURNING *""",
            (claims["sub"], body.reason.strip(), request_id))).fetchone()
    if row is None:
        await load_request(request_id)          # 404 se não existir
        raise HTTPException(status.HTTP_409_CONFLICT, "pedido já decidido")
    await record("CONTA_PEDIDO_REJEITADO", claims, request, request_id=str(request_id), kind=row["kind"],
                 user_id=str(row["user_id"]), reason=body.reason.strip())
    return jsonable(row)


@router.post("/admin/accounts", status_code=status.HTTP_201_CREATED)
async def open_account_at_desk(body: DirectAccountIn, request: Request,
                               claims: dict = Depends(require_permission("accounts:create:direct"))):
    """Abertura direta ao balcão: o operador abre a conta para um cliente ativo."""
    await client_status(str(body.user_id), request)
    account, created = await checked_open(str(body.user_id), body.region, body.currency, allow_existing=False)
    rid = uuid.uuid4()
    async with core.connection() as conn:   # o registo do pedido fica, para a rastreabilidade
        await conn.execute(
            """INSERT INTO account_requests (id, user_id, kind, region, currency, iban, status, created_by,
                   created_by_role, decided_by, decided_at, decision_reason)
               VALUES (%s, %s, 'ABERTURA', %s, %s, %s, 'APROVADO', %s, %s, %s, now(), 'abertura ao balcão')""",
            (rid, body.user_id, body.region, body.currency, account["iban"], claims["sub"], claims["role"], claims["sub"]))
    await record("CONTA_ABERTA_BALCAO", claims, request, request_id=str(rid), iban=account["iban"],
                 user_id=str(body.user_id), region=body.region, currency=body.currency)
    return {**account_out(account), "created": created, "request_id": str(rid)}
