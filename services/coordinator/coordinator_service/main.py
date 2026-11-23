"""2PC coordinator: the heart of the system.

POST /tx (signed by api-1/api-2 with Ed25519) executes one transfer:
  - same shard        -> normal local transaction (BEGIN ... COMMIT), kind=LOCAL
  - different shards  -> Two-Phase Commit, kind=DISTRIBUIDA

The durable log is the "transactions" table in pg-core: every state change is committed
there BEFORE acting on it. The commit of DECISAO_COMMIT is THE decision point:
  - crash before it  -> nobody decided to commit -> presumed abort (recovery rolls back)
  - crash after it   -> the decision exists     -> recovery carries out COMMIT PREPARED
"""
import asyncio
import json
import os
import ssl
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row

from common.audit import AuditLog
from common.crypto import check_signed_request, load_ed25519_private, load_ed25519_public, load_trusted_signers
from common import custody, limits
from common.db import REGIONS, make_pool, region_of_iban, shard_conninfo
from common.logging import add_request_logging, log_extra, setup_logging, tx_id_var
from common.reports import record as record_report

from . import logic, settlement
from .config import settings

log = setup_logging("coordinator")
audit = AuditLog("coordinator")
TRUSTED = load_trusted_signers(settings.public_keys_dir, list(settings.trusted_signers))

core = make_pool(
    f"host=pg-core.global.local dbname=coordinator user={settings.db_user} password={settings.db_password} "
    f"sslmode=verify-full sslrootcert={settings.ca_file} connect_timeout=3", max_size=20)
SHARD_DSN = {r: shard_conninfo(r, settings.db_user, settings.db_password, settings.ca_file) for r in REGIONS}
# Read-only (validate the accounts before starting): the primary or, if it is down, the replica.
# So a transfer enters the log and stays PENDENTE instead of being refused.
SHARD_READ_DSN = {r: shard_conninfo(r, settings.db_user, settings.db_password, settings.ca_file, read_only=True)
                  for r in REGIONS}
# Any node of the region answers: tells "primary down" (PENDENTE) from "region totally down" (custody).
ANY_NODE_DSN = SHARD_READ_DSN

# Settlement with the legacy partner bank (Java): our signing key + the bank's public key.
SIGNING_KEY = load_ed25519_private(settings.signing_key)
LEGACY_PUBLIC_KEY = load_ed25519_public(settings.legacy_public_key)
legacy = httpx.AsyncClient(base_url=settings.legacy_url, timeout=10,
                           verify=ssl.create_default_context(cafile=settings.ca_file))
settling: set[str] = set()             # settlements being sent right now
background: set[asyncio.Task] = set()  # keeps references so tasks are not garbage-collected

# Transactions being executed by THIS process right now. The recovery loop never touches
# them (e.g. a transaction paused by pause_after_prepare is not abandoned, only slow).
in_flight: set[str] = set()
# Back-pressure: at most N transfers at the same time (protects the shards' connections).
tx_slots = asyncio.Semaphore(settings.max_concurrent_tx)


@dataclass
class Chaos:
    """Fault injection for the demo. Kept in memory: after a crash the coordinator restarts
    with chaos off (otherwise crash_after_* would crash it again on every transfer)."""
    pause_before_prepare: int = 0          # pause before phase 1 (time to cut the network, scenario 13)
    pause_after_prepare: int = settings.chaos_pause_after_prepare
    crash_after_prepare: bool = settings.chaos_crash_after_prepare
    crash_after_decision: bool = settings.chaos_crash_after_decision
    fail_participant: str | None = settings.chaos_fail_participant


chaos = Chaos()


class ParticipantError(Exception):
    """A participant (shard) refused or failed during phase 1."""


@asynccontextmanager
async def lifespan(app: FastAPI):
    await core.open(wait=False)
    task = asyncio.create_task(recovery_loop())
    log.info(f"coordinator a arrancar; assinantes confiáveis={list(TRUSTED)} chaos={asdict(chaos)}")
    yield
    task.cancel()
    await core.close()


app = FastAPI(title="Global-Scale 2PC coordinator", lifespan=lifespan)
add_request_logging(app, log)


# --- limits configured by the administrator (settings table) -------------------------

_last_limits = dict(limits.DEFAULTS)


async def current_limits() -> dict:
    """Authoritative limits (the api also checks them, but the coordinator decides): max per
    transfer and daily limit per client, both in EUR. Read on every transfer, so an admin
    change applies to the very next one (on both api instances and here)."""
    global _last_limits
    try:
        async with core.connection() as conn:
            rows = await (await conn.execute("SELECT key, value FROM settings")).fetchall()
        _last_limits = {**limits.DEFAULTS, **{r["key"]: r["value"] for r in rows}}
    except Exception as exc:  # pg-core briefly unreachable: keep the last known values
        log.warning(f"limites indisponíveis, a usar os últimos conhecidos: {exc!r}")
    return _last_limits


# --- durable log ---------------------------------------------------------------------

async def event(tx_id, name: str, **detail) -> None:
    async with core.connection() as conn:
        await conn.execute("INSERT INTO tx_events (tx_id, event, detail) VALUES (%s, %s, %s)",
                           (tx_id, name, json.dumps(detail, default=str) if detail else None))
    log.info(f"[{name}] {detail if detail else ''}".strip(), extra=log_extra(tx_id=str(tx_id)))


async def set_state(tx_id, state: str, reason: str | None = None, **detail) -> None:
    """Commits the new state in pg-core (durable) and records the event."""
    async with core.connection() as conn:
        # A confirmed DISTRIBUTED transfer must then be settled with the partner bank.
        await conn.execute(
            "UPDATE transactions SET state = %s, failure_reason = COALESCE(%s, failure_reason), updated_at = now(), "
            "settlement_status = CASE WHEN %s = 'CONFIRMADA' AND kind = 'DISTRIBUIDA' AND settlement_status = 'N/A' "
            "THEN 'PENDENTE' ELSE settlement_status END WHERE tx_id = %s", (state, reason, state, tx_id))
    await event(tx_id, state, **({"reason": reason} if reason else {}), **detail)
    if state in ("CONFIRMADA", "ABORTADA"):
        tx = await load_tx(tx_id)
        await record_report("coordinator", {"type": "transfer", "state": state, "kind": tx["kind"],
                                            "region": tx["from_region"], "currency": tx["from_currency"],
                                            "amount": str(tx["amount"])})


async def load_tx(tx_id) -> dict | None:
    async with core.connection() as conn:
        return await (await conn.execute("SELECT * FROM transactions WHERE tx_id = %s", (tx_id,))).fetchone()


async def tx_view(tx_id) -> dict:
    async with core.connection() as conn:
        tx = await (await conn.execute("SELECT * FROM transactions WHERE tx_id = %s", (tx_id,))).fetchone()
        events = await (await conn.execute(
            "SELECT event, detail, at FROM tx_events WHERE tx_id = %s ORDER BY id", (tx_id,))).fetchall()
    out = {k: (str(v) if isinstance(v, (uuid.UUID, Decimal)) else v) for k, v in tx.items()}
    out["events"] = events
    return out


def response_for(view: dict, replay: bool = False) -> JSONResponse:
    code = {"CONFIRMADA": 200 if replay else 201, "ABORTADA": 422}.get(view["state"], 202)
    return JSONResponse(json.loads(json.dumps({**view, "idempotent_replay": replay}, default=str)), status_code=code)


# --- shards ----------------------------------------------------------------------------

async def connect_shard(region: str) -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(SHARD_DSN[region], row_factory=dict_row)


async def read_account(region: str, iban: str) -> dict | None:
    async with await psycopg.AsyncConnection.connect(SHARD_READ_DSN[region], row_factory=dict_row) as conn:
        return await (await conn.execute(
            "SELECT iban, user_id, currency, status FROM accounts WHERE iban = %s", (iban,))).fetchone()


async def apply_custody_leg(conn, tx: dict, side: str, iban: str) -> None:
    """One side of the transfer executed in CUSTODY: the account's region is totally down,
    so the money is debited from / credited to the custody account of `iban` in this shard."""
    debit = side == "DEBITO"
    status_ = tx["src_status"] if debit else tx["dst_status"]
    if status_ != "ATIVA":
        raise ParticipantError(f"conta de {'origem' if debit else 'destino'} {status_}")
    try:
        await custody.apply(
            conn, iban=iban, user_id=tx["src_user"] if debit else tx["dst_user"],
            currency=tx["from_currency"] if debit else tx["to_currency"], side=side,
            amount=tx["amount"] if debit else tx["converted_amount"], tx_id=tx["tx_id"],
            origin="TRANSFERENCIA", counterparty=tx["to_iban"] if debit else tx["from_iban"])
    except custody.CustodyError as exc:
        raise ParticipantError(str(exc)) from exc
    except psycopg.errors.LockNotAvailable as exc:
        raise ParticipantError("lock_timeout: valor retido bloqueado por outra transação") from exc


async def apply_any_leg(conn, tx: dict, exec_region: str, side: str, iban: str) -> None:
    if exec_region != region_of_iban(iban):
        await apply_custody_leg(conn, tx, side, iban)
    else:
        await apply_leg(conn, tx, side, iban)


def legs(tx: dict) -> list[tuple[str, str, str]]:
    """[(shard where it runs, side, iban)] in the global lock order."""
    return logic.plan_legs(tx["from_iban"], tx["to_iban"], tx["debit_region"] or tx["from_region"],
                           tx["credit_region"] or tx["to_region"])


async def apply_leg(conn, tx: dict, side: str, iban: str) -> None:
    """One side of the transfer inside the current transaction of `conn`:
    lock the account, validate, update the balance, write the movement."""
    debit = side == "DEBITO"
    amount = tx["amount"] if debit else tx["converted_amount"]
    currency = tx["from_currency"] if debit else tx["to_currency"]
    try:
        # FOR UPDATE: the row stays locked until COMMIT (or COMMIT PREPARED) — Isolation.
        account = await (await conn.execute(
            "SELECT * FROM accounts WHERE iban = %s FOR UPDATE", (iban,))).fetchone()
        if debit:
            today = (await (await conn.execute(
                """SELECT COALESCE(sum(amount), 0) AS total FROM movements
                   WHERE iban = %s AND type = 'DEBITO' AND origin = 'TRANSFERENCIA'
                     AND created_at >= date_trunc('day', now())""", (iban,))).fetchone())["total"]
            problem = logic.debit_problem(account, amount, today)
        else:
            problem = logic.credit_problem(account)
        if problem:
            raise ParticipantError(problem)
        new_balance = account["balance"] + (-amount if debit else amount)
        await conn.execute("UPDATE accounts SET balance = %s WHERE iban = %s", (new_balance, iban))
        await conn.execute(
            """INSERT INTO movements (iban, tx_id, type, amount, currency, balance_after, origin)
               VALUES (%s, %s, %s, %s, %s, %s, 'TRANSFERENCIA')""",
            (iban, tx["tx_id"], side, amount, currency, new_balance))
    except psycopg.errors.LockNotAvailable as exc:
        raise ParticipantError("lock_timeout: conta bloqueada por outra transação") from exc
    except psycopg.errors.QueryCanceled as exc:
        raise ParticipantError("statement_timeout") from exc
    except psycopg.errors.CheckViolation as exc:
        raise ParticipantError(f"restrição violada: {exc.diag.constraint_name}") from exc


# --- LOCAL ----------------------------------------------------------------------------

async def run_local(tx: dict) -> None:
    region = tx["debit_region"] or tx["from_region"]
    try:
        async with await connect_shard(region) as conn:
            async with conn.transaction():          # BEGIN ... COMMIT in ONE shard
                for exec_region, side, iban in legs(tx):  # ordered by IBAN
                    await apply_any_leg(conn, tx, exec_region, side, iban)
        await set_state(tx["tx_id"], "CONFIRMADA", shard=region)
    except ParticipantError as exc:
        await set_state(tx["tx_id"], "ABORTADA", str(exc))
    except psycopg.OperationalError as exc:
        await mark_pending(tx, region, type(exc).__name__)


async def mark_pending(tx: dict, region: str, reason: str) -> None:
    """Um nó não responde: a transferência não é abortada, fica PENDENTE (sem movimentos e sem
    bloqueios) e o recovery loop conclui-a quando todos os nós voltarem a responder."""
    await event(tx["tx_id"], f"AGUARDA_NO_{region}", reason=reason)
    await set_state(tx["tx_id"], "PENDENTE", f"nó {region} indisponível ({reason}): será concluída quando o nó voltar")


# --- DISTRIBUIDA: Two-Phase Commit --------------------------------------------------------

async def prepare_leg(tx: dict, region: str, side: str, iban: str) -> psycopg.AsyncConnection:
    """Phase 1 on one shard: BEGIN (with a global xid) ... PREPARE TRANSACTION.
    After PREPARE the shard has promised it can commit, and keeps the locks."""
    conn = await connect_shard(region)
    try:
        xid = conn.xid(1, str(tx["tx_id"]), region)   # gid = format 1, gtrid = tx_id, bqual = region
        await conn.tpc_begin(xid)
        await apply_any_leg(conn, tx, region, side, iban)
        if chaos.fail_participant == region:
            raise ParticipantError(f"falha injetada no participante {region} (chaos)")
        await conn.tpc_prepare()
        return conn
    except BaseException:
        try:
            await conn.tpc_rollback()               # not prepared yet: a plain ROLLBACK
        except Exception:
            pass
        await conn.close()
        raise


async def run_2pc(tx: dict) -> None:
    tx_id = tx["tx_id"]
    await set_state(tx_id, "PREPARANDO")
    prepared: dict[str, psycopg.AsyncConnection] = {}
    if chaos.pause_before_prepare:
        await event(tx_id, "PAUSA_CHAOS_ANTES_PREPARE", seconds=chaos.pause_before_prepare)
        await asyncio.sleep(chaos.pause_before_prepare)

    # ---- Phase 1: PREPARE, one shard after the other in the global order (EU, AM, AF) ----
    failure = None
    unavailable = None          # region that did not answer (not a NO vote)
    for region, side, iban in legs(tx):
        try:
            prepared[region] = await asyncio.wait_for(prepare_leg(tx, region, side, iban),
                                                      settings.participant_timeout)
            await event(tx_id, f"PREPARADO_{region}", side=side, iban=iban)
        except ParticipantError as exc:
            failure = f"{region}: {exc}"
        except asyncio.TimeoutError:
            failure, unavailable = f"timeout na fase 1 ({settings.participant_timeout}s)", region
        except psycopg.OperationalError as exc:
            failure, unavailable = f"shard indisponível ({type(exc).__name__})", region
        if failure:
            if not unavailable:
                await event(tx_id, f"VOTO_NAO_{region}", reason=failure)
            break

    if failure:
        # Someone voted NO: roll back everyone who prepared, then ABORTADA.
        for region, conn in prepared.items():
            try:
                await conn.tpc_rollback()
                await event(tx_id, f"ROLLBACK_{region}")
            except Exception as exc:  # the recovery loop will find it as an orphan
                await event(tx_id, f"ROLLBACK_FALHOU_{region}", error=repr(exc))
            await conn.close()
        if unavailable:
            await mark_pending(tx, unavailable, failure)
        else:
            await set_state(tx_id, "ABORTADA", failure)
        return

    # ---- Everyone voted YES ----
    if chaos.pause_after_prepare:
        await event(tx_id, "PAUSA_CHAOS", seconds=chaos.pause_after_prepare)
        await asyncio.sleep(chaos.pause_after_prepare)
    if chaos.crash_after_prepare:
        log.error("CHAOS: crash depois do PREPARE, antes da decisão", extra=log_extra(tx_id=str(tx_id)))
        os._exit(1)

    # ---- Decision point: durable commit of DECISAO_COMMIT in pg-core ----
    try:
        await set_state(tx_id, "DECISAO_COMMIT")
    except Exception as exc:
        # Could not record the decision -> nobody can rely on it -> abort.
        log.error(f"não foi possível gravar a decisão: {exc!r}", extra=log_extra(tx_id=str(tx_id)))
        for conn in prepared.values():
            try:
                await conn.tpc_rollback()
            finally:
                await conn.close()
        try:
            await set_state(tx_id, "ABORTADA", "log do coordenador indisponível na decisão")
        except Exception:
            pass  # stays PREPARANDO: the recovery loop aborts it later (presumed abort)
        return

    if chaos.crash_after_decision:
        log.error("CHAOS: crash depois da DECISAO_COMMIT, antes dos COMMIT PREPARED",
                  extra=log_extra(tx_id=str(tx_id)))
        os._exit(1)

    # ---- Phase 2: COMMIT PREPARED on every shard ----
    pending = []
    for region, conn in prepared.items():
        try:
            await conn.tpc_commit()
            await event(tx_id, f"COMMIT_{region}")
        except Exception as exc:
            # The decision is already durable: the recovery loop will finish it.
            pending.append(region)
            await event(tx_id, f"COMMIT_PENDENTE_{region}", error=type(exc).__name__)
        finally:
            await conn.close()
    if not pending:
        await set_state(tx_id, "CONFIRMADA")


# --- routing: direct, or in custody when the account's region is totally down ---------------

_down_until: dict[str, float] = {}     # region -> monotonic time until which it counts as down
DOWN_CACHE_SECONDS = 5


async def region_down(region: str) -> bool:
    """True only when NO node of the region answers (primary AND replica). A primary that is
    down while its replica answers is a failover case: writes wait for the promotion."""
    if time.monotonic() < _down_until.get(region, 0):
        return True
    try:
        async with await psycopg.AsyncConnection.connect(ANY_NODE_DSN[region]) as conn:
            await conn.execute("SELECT 1")
        _down_until.pop(region, None)
        return False
    except psycopg.OperationalError:
        _down_until[region] = time.monotonic() + DOWN_CACHE_SECONDS
        return True


async def directory_account(iban: str) -> dict | None:
    async with core.connection() as conn:
        return await (await conn.execute(
            "SELECT iban, user_id, currency, status FROM account_directory WHERE iban = %s", (iban,))).fetchone()


async def custody_holdings(iban: str) -> tuple[dict[str, Decimal], list[str]]:
    """({shard: amount held for iban}, active shards), over the shards of the other regions."""
    holding, reachable = {}, []
    for region in custody.other_regions(region_of_iban(iban)):
        if time.monotonic() < _down_until.get(region, 0):
            continue
        try:
            async with await connect_shard(region) as conn:
                balance = await custody.holdings(conn, iban)
        except psycopg.OperationalError:
            continue
        reachable.append(region)
        if balance is not None:
            holding[region] = balance
    return holding, reachable


async def resolve(iban: str, side: str, amount: Decimal) -> tuple[dict | None, str, bool]:
    """(account, shard where this leg runs, in custody?).
    The account's own shard if it answers; if its region is totally down, the account is
    validated in the directory and the leg runs in custody in another active shard."""
    region = region_of_iban(iban)
    if time.monotonic() >= _down_until.get(region, 0):
        try:
            return await read_account(region, iban), region, False
        except psycopg.OperationalError:
            if not await region_down(region):
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                    f"shard {region} indisponível (primário em baixo, a aguardar failover)")
    account = await directory_account(iban)
    if account is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"região {region} indisponível e a conta não está no diretório")
    holding, reachable = await custody_holdings(iban)
    if side == "CREDITO":
        holder = custody.credit_holder(region, reachable, holding)
    else:
        holder = custody.debit_holder(holding, amount)
    if holder is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"região {region} indisponível" + ("" if side == "CREDITO"
                                                               else " e sem valor retido para esta conta"))
    log.warning(f"região {region} em baixo: {side.lower()} de {iban} em custódia no shard {holder}")
    return account, holder, True


# --- POST /tx -------------------------------------------------------------------------

@app.post("/tx")
async def submit(request: Request):
    body = await request.body()
    ok, reason = check_signed_request(body, request.headers, TRUSTED)
    if not ok:
        log.warning(f"ADULTERACAO_DETETADA: {reason}", extra=log_extra(signer=request.headers.get("x-signer")))
        await audit.write("ADULTERACAO_DETETADA", reason=reason, signer=request.headers.get("x-signer"),
                          sha256_received=request.headers.get("x-payload-sha256"))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"pedido rejeitado: {reason}")

    payload = json.loads(body)
    # The maximum is in EUR: checked in process_transfer, once the source currency is known.
    if problem := logic.payload_problem(payload, logic.utcnow(), None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    tx_id_var.set(payload["tx_id"])

    async with tx_slots:
        return await process_transfer(payload, request.headers)


async def process_transfer(payload: dict, headers) -> JSONResponse:
    key = logic.scoped_idempotency_key(payload["user_id"], payload["idempotency_key"])
    amount = Decimal(payload["amount"])

    # Idempotency: the same key never executes twice.
    async with core.connection() as conn:
        existing = await (await conn.execute(
            "SELECT * FROM transactions WHERE idempotency_key = %s", (key,))).fetchone()
    if existing:
        if (existing["from_iban"], existing["to_iban"], existing["amount"]) != (payload["from_iban"], payload["to_iban"], amount):
            raise HTTPException(status.HTTP_409_CONFLICT, "Idempotency-Key já usada com outros dados")
        await event(existing["tx_id"], "PEDIDO_REPETIDO", signer=headers.get("x-signer"))
        return response_for(await tx_view(existing["tx_id"]), replay=True)

    from_region, to_region = region_of_iban(payload["from_iban"]), region_of_iban(payload["to_iban"])
    # Where each leg runs: in the account's region, or in custody in another shard when that
    # region is totally down (primary AND replica).
    src, debit_region, src_custody = await resolve(payload["from_iban"], "DEBITO", amount)
    dst, credit_region, dst_custody = await resolve(payload["to_iban"], "CREDITO", amount)
    if src is None or dst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conta de origem ou destino não existe")

    # Exchange rate (fixed in the log at this moment)
    rate = Decimal(1)
    if src["currency"] != dst["currency"]:
        async with core.connection() as conn:
            row = await (await conn.execute("SELECT rate FROM fx_rates WHERE base = %s AND quote = %s",
                                            (src["currency"], dst["currency"]))).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "sem taxa de câmbio")
        rate = row["rate"]

    # Limits in EUR (max per transfer; daily limit per client, summed over all their accounts).
    eur_rate = Decimal(1)
    if src["currency"] != "EUR":
        async with core.connection() as conn:
            row = await (await conn.execute(limits.EUR_RATE_SQL, (src["currency"],))).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "sem taxa de câmbio para EUR")
        eur_rate = row["rate"]
    amount_eur = limits.to_eur(amount, eur_rate)
    conf = await current_limits()
    if problem := limits.max_problem(amount_eur, conf["max_transfer_amount"]):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    own_transfer = str(src["user_id"]) == str(dst["user_id"])

    tx = {
        "tx_id": uuid.UUID(payload["tx_id"]), "idempotency_key": key, "user_id": payload["user_id"],
        "from_iban": payload["from_iban"], "to_iban": payload["to_iban"],
        "from_region": from_region, "to_region": to_region, "amount": amount,
        "from_currency": src["currency"], "to_currency": dst["currency"],
        "fx_rate": rate, "converted_amount": logic.convert(amount, rate),
        # LOCAL / DISTRIBUIDA by where the legs actually run (one shard or two).
        "kind": logic.transfer_kind(debit_region, credit_region),
        "debit_region": debit_region, "credit_region": credit_region,
        "routing": "CUSTODIA" if (src_custody or dst_custody) else "DIRETA",
        "src_status": src["status"], "dst_status": dst["status"],
        "src_user": src["user_id"], "dst_user": dst["user_id"],
        # Rastreabilidade: quem submeteu a ordem e quem a aprovou (assinado pela api).
        "initiated_by": payload.get("initiated_by") or payload["user_id"],
        "initiated_role": payload.get("initiated_role") or "cliente",
        "approved_by": payload.get("approved_by"),
        "request_id": payload.get("request_id"),
        "amount_eur": amount_eur, "own_transfer": own_transfer,
    }

    in_flight.add(payload["tx_id"])
    try:
        # INICIADA, committed immediately: from now on the transaction exists in the log.
        # The daily limit per client is checked in the SAME transaction, under a lock per
        # client: two concurrent transfers from different accounts of the same client are
        # serialised here, so together they can never go over the limit.
        over_limit = None
        async with core.connection() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext('daily:' || %s))", (str(tx["user_id"]),))
                if not own_transfer:
                    sent = (await (await conn.execute(limits.SENT_TODAY_SQL, (tx["user_id"],))).fetchone())["total"]
                    over_limit = limits.daily_problem(sent, amount_eur, conf["daily_limit_eur"])
                inserted = await (await conn.execute(
                    """INSERT INTO transactions (tx_id, idempotency_key, user_id, from_iban, to_iban, from_region,
                           to_region, amount, from_currency, to_currency, fx_rate, converted_amount, kind, state,
                           request_signature, request_sha256, initiated_by, initiated_role, approved_by, request_id,
                           amount_eur, own_transfer, routing, debit_region, credit_region)
                       VALUES (%(tx_id)s, %(idempotency_key)s, %(user_id)s, %(from_iban)s, %(to_iban)s, %(from_region)s,
                           %(to_region)s, %(amount)s, %(from_currency)s, %(to_currency)s, %(fx_rate)s,
                           %(converted_amount)s, %(kind)s, 'INICIADA', %(sig)s, %(sha)s, %(initiated_by)s,
                           %(initiated_role)s, %(approved_by)s, %(request_id)s, %(amount_eur)s, %(own_transfer)s,
                           %(routing)s, %(debit_region)s, %(credit_region)s)
                       ON CONFLICT DO NOTHING RETURNING tx_id""",
                    {**tx, "sig": headers.get("x-signature"), "sha": headers.get("x-payload-sha256")})).fetchone()
        if inserted is None:  # the same request arrived twice at the same time
            return response_for(await tx_view(tx["tx_id"]), replay=True)
        await event(tx["tx_id"], "INICIADA", kind=tx["kind"], amount=str(amount), from_currency=tx["from_currency"],
                    to_currency=tx["to_currency"], fx_rate=str(rate), converted=str(tx["converted_amount"]),
                    signer=headers.get("x-signer"), initiated_by=tx["initiated_by"], initiated_role=tx["initiated_role"],
                    approved_by=tx["approved_by"])
        if tx["routing"] == "CUSTODIA":
            # Where the money came from, where it was going, and where it is kept meanwhile.
            await event(tx["tx_id"], "DESVIO_CUSTODIA",
                        debito={"conta": tx["from_iban"], "regiao": from_region, "executado_em": debit_region},
                        credito={"conta": tx["to_iban"], "regiao": to_region, "executado_em": credit_region},
                        motivo="região totalmente indisponível (primário e réplica)")

        if over_limit:
            await set_state(tx["tx_id"], "ABORTADA", over_limit)   # logged, never executed
        elif tx["kind"] == "LOCAL":
            await run_local(tx)
        else:
            await run_2pc(tx)
    finally:
        in_flight.discard(payload["tx_id"])

    view = await tx_view(tx["tx_id"])
    if view["settlement_status"] == "PENDENTE":
        start_settlement(payload["tx_id"])     # asynchronous: the client does not wait for it
    await audit.write("TRANSFERENCIA", tx_id=payload["tx_id"], kind=tx["kind"], routing=tx["routing"],
                      debit_region=debit_region, credit_region=credit_region, state=view["state"],
                      actor=tx["initiated_by"], actor_role=tx["initiated_role"], approved_by=tx["approved_by"],
                      result="OK" if view["state"] == "CONFIRMADA" else view["state"],
                      from_iban=tx["from_iban"], to_iban=tx["to_iban"], amount=str(amount),
                      currency=tx["from_currency"], reason=view.get("failure_reason"))
    return response_for(view)


# --- Settlement with the legacy bank (asynchronous) ----------------------------------------

def start_settlement(tx_id: str) -> None:
    task = asyncio.create_task(settle(tx_id))
    background.add(task)
    task.add_done_callback(background.discard)


async def settle(tx_id: str) -> None:
    """Sends the signed XML order and records the bank's signed answer.
    On network failure the status stays PENDENTE and the recovery loop retries."""
    if tx_id in settling:
        return
    settling.add(tx_id)
    try:
        tx = await load_tx(tx_id)
        if tx is None or tx["settlement_status"] != "PENDENTE":
            return
        timestamp = settlement.utc_timestamp()
        xml = settlement.build_order_xml(tx, timestamp, SIGNING_KEY)
        try:
            response = await legacy.post("/settlement", content=xml,
                                         headers={"Content-Type": "application/xml; charset=utf-8"})
        except httpx.HTTPError as exc:
            log.warning(f"banco parceiro indisponível ({type(exc).__name__}); liquidação fica PENDENTE",
                        extra=log_extra(tx_id=tx_id))
            return
        ack = settlement.parse_ack(response.content)
        ok, reason = settlement.verify_ack(ack, LEGACY_PUBLIC_KEY)
        if not ok or ack["tx_id"] != tx_id:
            await event(tx_id, "LIQUIDACAO_ACK_INVALIDO", reason=reason if not ok else "tx_id diferente")
            await audit.write("ADULTERACAO_DETETADA", tx_id=tx_id, reason=f"ack do legado: {reason}")
            return
        async with core.connection() as conn:
            await conn.execute("UPDATE transactions SET settlement_status = %s, updated_at = now() "
                               "WHERE tx_id = %s AND settlement_status = 'PENDENTE'", (ack["status"], tx_id))
        await event(tx_id, f"LIQUIDACAO_{ack['status']}", reason=ack["reason"], http=response.status_code,
                    bank_timestamp=ack["timestamp"])
        await audit.write("LIQUIDACAO", tx_id=tx_id, status=ack["status"], reason=ack["reason"])
    except Exception as exc:
        log.warning(f"liquidação falhou: {exc!r}", extra=log_extra(tx_id=tx_id))
    finally:
        settling.discard(tx_id)


async def retry_pending_settlements() -> None:
    async with core.connection() as conn:
        rows = await (await conn.execute(
            "SELECT tx_id FROM transactions WHERE settlement_status = 'PENDENTE' "
            "AND updated_at < now() - interval '5 seconds' ORDER BY updated_at LIMIT 20")).fetchall()
    for row in rows:
        await settle(str(row["tx_id"]))


# --- Recovery loop (presumed abort) -------------------------------------------------------

shard_failures = {r: 0 for r in REGIONS}
shard_next_try = {r: 0.0 for r in REGIONS}


FORWARD_FORMAT = 2   # xid format of the custody forwards (transfers use format 1)


async def open_available_shards() -> dict[str, tuple[psycopg.AsyncConnection, dict, dict]]:
    """Connects to every shard that is not in back-off;
    returns {region: (conn, prepared transfer xids, prepared forward xids)}."""
    out = {}
    for region in REGIONS:
        if time.monotonic() < shard_next_try[region]:
            continue
        try:
            conn = await connect_shard(region)
            await conn.set_autocommit(True)
            recovered = [x for x in await conn.tpc_recover() if x.bqual == region]
            xids = {x.gtrid: x for x in recovered if x.format_id == 1}
            forward_xids = {x.gtrid: x for x in recovered if x.format_id == FORWARD_FORMAT}
            out[region] = (conn, xids, forward_xids)
            if shard_failures[region]:
                log.info(f"recovery: shard {region} acessível de novo")
            shard_failures[region] = 0
        except Exception as exc:
            shard_failures[region] += 1
            wait = logic.backoff_seconds(shard_failures[region])
            shard_next_try[region] = time.monotonic() + wait
            log.warning(f"recovery: shard {region} inacessível ({type(exc).__name__}); nova tentativa em {wait}s")
    return out


async def movement_exists(conn, tx_id) -> bool:
    row = await (await conn.execute(
        "SELECT (SELECT count(*) FROM movements WHERE tx_id = %s) + "
        "(SELECT count(*) FROM custody_movements WHERE tx_id = %s) AS n", (tx_id, tx_id))).fetchone()
    return row["n"] > 0


async def recover_one(tx: dict, shards: dict) -> None:
    tx_id, gtrid = tx["tx_id"], str(tx["tx_id"])
    debit_region = tx.get("debit_region") or tx["from_region"]
    credit_region = tx.get("credit_region") or tx["to_region"]
    regions = sorted({debit_region, credit_region}, key=logic.REGION_ORDER.index)
    age = (logic.utcnow() - tx["updated_at"]).total_seconds()
    action = logic.recovery_action(tx["state"], tx["kind"], age)
    if action == "WAIT" or any(r not in shards for r in regions):
        return  # too early, or a participant is unreachable: try again in the next pass
    tx_id_var.set(gtrid)

    if action == "COMMIT":
        for region in regions:
            conn, xids, _ = shards[region]
            if gtrid in xids:
                await conn.tpc_commit(xids.pop(gtrid))
                await event(tx_id, f"RECUPERACAO_COMMIT_{region}")
            elif not await movement_exists(conn, tx_id):
                await event(tx_id, f"ALERTA_SEM_PREPARADA_{region}")   # should never happen
        await set_state(tx_id, "CONFIRMADA", recovered=True)

    elif action == "ABORT":
        for region in regions:
            conn, xids, _ = shards[region]
            if gtrid in xids:
                await conn.tpc_rollback(xids.pop(gtrid))
                await event(tx_id, f"RECUPERACAO_ROLLBACK_{region}")
        await set_state(tx_id, "ABORTADA", f"recuperação: presumed abort ({tx['state']} há {int(age)}s sem decisão)")

    elif action == "CHECK_LOCAL":
        conn, _, _ = shards[debit_region]
        committed = await movement_exists(conn, tx_id)  # local tx is atomic: all movements or none
        if committed:
            await set_state(tx_id, "CONFIRMADA", recovered=True)
        else:
            await set_state(tx_id, "ABORTADA", "recuperação: transação local não chegou a fazer commit")


async def recovery_pass() -> None:
    async with core.connection() as conn:
        unfinished = await (await conn.execute(
            "SELECT * FROM transactions WHERE state IN ('INICIADA','PREPARANDO','DECISAO_COMMIT') "
            "ORDER BY created_at")).fetchall()
    unfinished = [t for t in unfinished if str(t["tx_id"]) not in in_flight]
    shards = await open_available_shards()
    try:
        for tx in unfinished:
            try:
                await recover_one(tx, shards)
            except Exception as exc:
                log.warning(f"recovery de {tx['tx_id']} falhou: {exc!r}")

        await recover_forwards(shards)

        # Orphans: prepared transactions in a shard not handled above.
        for region, (conn, xids, _) in shards.items():
            for gtrid, xid in list(xids.items()):
                if gtrid in in_flight:
                    continue
                tx = await load_tx(gtrid)
                age = (logic.utcnow() - tx["updated_at"]).total_seconds() if tx else None
                action = logic.orphan_action(tx["state"] if tx else None, age)
                if action == "SKIP":
                    continue
                if action == "COMMIT":
                    await conn.tpc_commit(xid)
                else:
                    await conn.tpc_rollback(xid)
                log.warning(f"recovery: preparada órfã {gtrid} em {region} -> {action}")
                if tx:
                    await event(tx["tx_id"], f"ORFA_{action}_{region}")

        # Custody: send what was kept for a region that is reachable again.
        await forward_custody(shards)
        await sync_directory(shards)
    finally:
        for conn, _, _ in shards.values():
            await conn.close()

    await resume_pending(set(shards))


async def add_custody_fields(tx: dict) -> None:
    """A leg in custody needs the owner and status of the account (from the directory): a
    transaction read back from the log does not carry them."""
    for side, iban in (("src", tx["from_iban"]), ("dst", tx["to_iban"])):
        row = await directory_account(iban)
        tx[f"{side}_status"] = row["status"] if row else "DESCONHECIDA"
        tx[f"{side}_user"] = row["user_id"] if row else None


async def resume_pending(reachable: set) -> None:
    """Transferências PENDENTE (um nó estava em baixo): quando TODOS os nós envolvidos voltam a
    responder, executa-as de novo (LOCAL ou 2PC) até ficarem CONFIRMADA (ou ABORTADA por saldo,
    limites, etc.). Nunca duplicam: a mesma linha do log, o mesmo tx_id."""
    async with core.connection() as conn:
        pending = await (await conn.execute(
            "SELECT * FROM transactions WHERE state = 'PENDENTE' ORDER BY created_at")).fetchall()
    for tx in pending:
        tx_id = str(tx["tx_id"])
        # The shards where the legs run (in custody: not the account's region, which may still be down).
        where = {tx.get("debit_region") or tx["from_region"], tx.get("credit_region") or tx["to_region"]}
        if tx_id in in_flight or not where <= reachable:
            continue
        in_flight.add(tx_id)
        try:
            if tx.get("routing") == "CUSTODIA":
                await add_custody_fields(tx)
            async with core.connection() as conn:
                await conn.execute("UPDATE transactions SET failure_reason = NULL WHERE tx_id = %s", (tx["tx_id"],))
            await event(tx["tx_id"], "RETOMADA", reason="nós disponíveis de novo")
            if tx["kind"] == "LOCAL":
                await run_local(tx)
            else:
                await run_2pc(tx)
            view = await tx_view(tx["tx_id"])
            log.info(f"recovery: transferência pendente retomada -> {view['state']}", extra=log_extra(tx_id=tx_id))
            if view["settlement_status"] == "PENDENTE":
                start_settlement(tx_id)
            await audit.write("TRANSFERENCIA_RETOMADA", tx_id=tx_id, state=view["state"], reason=view.get("failure_reason"))
        except Exception as exc:
            log.warning(f"recovery: retomar {tx_id} falhou: {exc!r}")
        finally:
            in_flight.discard(tx_id)


# --- Custody: forward to the destination region when it is back ------------------------------
#
# A forward is a 2PC of its own (xid format 2) between the shard that kept the money
# (holder) and the account's region (target):
#   holder: custody balance -> 0, pending movements marked as forwarded
#   target: the pending movements replayed in the account's statement (via_region = holder),
#           balance += remaining amount
# Durable log: custody_forwards in pg-core (PREPARANDO -> DECISAO_COMMIT -> CONCLUIDO), same
# presumed-abort recovery as the transfers.

forward_retry_at: dict[str, float] = {}       # target iban -> do not retry before (after a failure)
FORWARD_RETRY_SECONDS = 60


async def forward_state(fid, state: str, reason: str | None = None, **values) -> None:
    sets = ", ".join(f"{k} = %({k})s" for k in values)
    async with core.connection() as conn:
        await conn.execute(
            f"UPDATE custody_forwards SET state = %(state)s, reason = COALESCE(%(reason)s, reason), "
            f"updated_at = now(){', ' + sets if sets else ''} WHERE forward_id = %(fid)s",
            {"state": state, "reason": reason, "fid": fid, **values})


async def forward_custody(shards: dict) -> None:
    for holder, (conn, _, _) in shards.items():
        try:
            pending = await (await conn.execute(
                """SELECT DISTINCT c.target_iban, c.target_region FROM custody_accounts c
                   JOIN custody_movements m ON m.target_iban = c.target_iban AND m.forwarded_by IS NULL""")).fetchall()
        except psycopg.errors.UndefinedTable:
            return   # migrations not applied yet
        for row in pending:
            iban, target = row["target_iban"], row["target_region"]
            if target not in shards or time.monotonic() < forward_retry_at.get(iban, 0):
                continue      # destination still down (or failed recently): keep it in custody
            try:
                await forward_one(holder, iban, target)
            except Exception as exc:
                forward_retry_at[iban] = time.monotonic() + FORWARD_RETRY_SECONDS
                log.warning(f"reencaminhamento de {iban} ({holder} -> {target}) falhou: {exc!r}")


async def forward_one(holder: str, iban: str, target: str) -> None:
    fid = uuid.uuid4()
    async with core.connection() as conn:
        await conn.execute(
            """INSERT INTO custody_forwards (forward_id, holder_region, target_iban, target_region, state)
               VALUES (%s, %s, %s, %s, 'PREPARANDO')""", (fid, holder, iban, target))
    in_flight.add(str(fid))
    prepared: dict[str, psycopg.AsyncConnection] = {}
    try:
        # ---- Phase 1. Holder first: it locks the custody account and reads the history. ----
        try:
            hconn = await connect_shard(holder)
            prepared[holder] = hconn
            await hconn.tpc_begin(hconn.xid(FORWARD_FORMAT, str(fid), holder))
            box = await (await hconn.execute(
                "SELECT * FROM custody_accounts WHERE target_iban = %s FOR UPDATE", (iban,))).fetchone()
            moves = await (await hconn.execute(
                "SELECT * FROM custody_movements WHERE target_iban = %s AND forwarded_by IS NULL ORDER BY id",
                (iban,))).fetchall()
            if not moves:
                raise custody.CustodyError("nada a reencaminhar")
            if custody.net_of(moves) != box["balance"]:
                raise custody.CustodyError(f"saldo retido {box['balance']} difere do histórico {custody.net_of(moves)}")
            await hconn.execute("UPDATE custody_movements SET forwarded_by = %s WHERE id = ANY(%s)",
                                (fid, [m["id"] for m in moves]))
            if box["balance"] > 0:
                await hconn.execute(
                    """INSERT INTO custody_movements (target_iban, tx_id, type, amount, currency, balance_after,
                           origin, counterparty, forwarded_by)
                       VALUES (%s, %s, 'DEBITO', %s, %s, 0, 'REENCAMINHAMENTO', %s, %s)""",
                    (iban, fid, box["balance"], box["currency"], iban, fid))
            await hconn.execute("UPDATE custody_accounts SET balance = 0, updated_at = now() WHERE target_iban = %s",
                                (iban,))
            await hconn.tpc_prepare()

            tconn = await connect_shard(target)
            prepared[target] = tconn
            await tconn.tpc_begin(tconn.xid(FORWARD_FORMAT, str(fid), target))
            account = await (await tconn.execute(
                "SELECT * FROM accounts WHERE iban = %s FOR UPDATE", (iban,))).fetchone()
            if account is None or account["status"] == "ENCERRADA":
                raise custody.CustodyError(f"conta de destino {'inexistente' if account is None else 'ENCERRADA'}")
            if account["currency"] != box["currency"]:
                raise custody.CustodyError("moeda da conta difere da custódia")
            replayed, final = custody.replay(account["balance"], moves)
            for r in replayed:
                m = r.move
                await tconn.execute(
                    """INSERT INTO movements (iban, tx_id, type, amount, currency, balance_after, origin, via_region,
                           created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (iban, m["tx_id"], m["type"], m["amount"], m["currency"], r.balance_after, m["origin"], holder,
                     m["created_at"]))
            await tconn.execute("UPDATE accounts SET balance = %s WHERE iban = %s", (final, iban))
            await tconn.tpc_prepare()
        except Exception as exc:
            for conn in prepared.values():
                try:
                    await conn.tpc_rollback()
                except Exception:
                    pass   # left prepared: the recovery finds it (ABORTADO -> rollback)
            await forward_state(fid, "ABORTADO", repr(exc) if not isinstance(exc, custody.CustodyError) else str(exc))
            raise

        # ---- Decision point ----
        await forward_state(fid, "DECISAO_COMMIT", amount=box["balance"], currency=box["currency"],
                            movements=len(moves))
        # ---- Phase 2 ----
        pending = []
        for region, conn in prepared.items():
            try:
                await conn.tpc_commit()
            except Exception:
                pending.append(region)       # the decision is durable: recovery finishes it
        if not pending:
            await forward_state(fid, "CONCLUIDO")
        forward_retry_at.pop(iban, None)
        log.info(f"custódia reencaminhada: {iban} {holder} -> {target}: {len(moves)} movimentos, "
                 f"saldo restante {box['balance']} {box['currency']}")
        tx_ids = list({m["tx_id"] for m in moves})
        async with core.connection() as conn:
            # Timeline of each transfer involved: it now really is in the destination region.
            await conn.execute(
                "INSERT INTO tx_events (tx_id, event, detail) SELECT tx_id, %s, %s FROM transactions WHERE tx_id = ANY(%s)",
                (f"REENCAMINHADA_PARA_{target}",
                 json.dumps({"de": holder, "conta": iban, "reencaminhamento": str(fid)}), tx_ids))
        await audit.write("CUSTODIA_REENCAMINHADA", forward_id=str(fid), iban=iban, holder=holder, target=target,
                          amount=str(box["balance"]), currency=box["currency"], movements=len(moves))
    finally:
        in_flight.discard(str(fid))
        for conn in prepared.values():
            await conn.close()


FORWARD_AS_TX_STATE = {"CONCLUIDO": "CONFIRMADA", "ABORTADO": "ABORTADA"}


async def recover_forwards(shards: dict) -> None:
    """Forwards interrupted by a crash (same rules as the transfers: presumed abort)."""
    try:
        async with core.connection() as conn:
            rows = await (await conn.execute("SELECT * FROM custody_forwards")).fetchall()
    except psycopg.errors.UndefinedTable:
        return
    by_id = {str(r["forward_id"]): r for r in rows}
    for row in rows:
        fid = str(row["forward_id"])
        if row["state"] not in ("PREPARANDO", "DECISAO_COMMIT") or fid in in_flight:
            continue
        regions = (row["holder_region"], row["target_region"])
        if any(r not in shards for r in regions):
            continue
        age = (logic.utcnow() - row["updated_at"]).total_seconds()
        action = logic.recovery_action(row["state"], "DISTRIBUIDA", age)
        if action == "WAIT":
            continue
        for region in regions:
            conn, _, fxids = shards[region]
            if fid in fxids:
                xid = fxids.pop(fid)
                await (conn.tpc_commit(xid) if action == "COMMIT" else conn.tpc_rollback(xid))
        await forward_state(row["forward_id"], "CONCLUIDO" if action == "COMMIT" else "ABORTADO",
                            None if action == "COMMIT" else "recuperação: presumed abort")
        log.warning(f"recovery: reencaminhamento {fid} -> {action}")
    # Prepared forwards the log does not account for.
    for region, (conn, _, fxids) in shards.items():
        for fid, xid in list(fxids.items()):
            if fid in in_flight:
                continue
            row = by_id.get(fid)
            state = FORWARD_AS_TX_STATE.get(row["state"], row["state"]) if row else None
            age = (logic.utcnow() - row["updated_at"]).total_seconds() if row else None
            action = logic.orphan_action(state, age)
            if action == "COMMIT":
                await conn.tpc_commit(xid)
            elif action == "ROLLBACK":
                await conn.tpc_rollback(xid)


# --- Account directory (validates accounts of a region that is down) -------------------------

DIRECTORY_SYNC_SECONDS = 30
_last_directory_sync = 0.0


async def sync_directory(shards: dict) -> None:
    """Copies iban -> owner, currency, status of every reachable shard to pg-core. The api
    also writes it when it creates an account; this keeps status changes up to date."""
    global _last_directory_sync
    if time.monotonic() - _last_directory_sync < DIRECTORY_SYNC_SECONDS:
        return
    _last_directory_sync = time.monotonic()
    for region, (conn, _, _) in shards.items():
        rows = await (await conn.execute("SELECT iban, user_id, currency, status FROM accounts")).fetchall()
        if not rows:
            continue
        async with core.connection() as cconn:
            async with cconn.cursor() as cur:
                await cur.executemany(
                    """INSERT INTO account_directory (iban, user_id, region, currency, status)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (iban) DO UPDATE SET user_id = EXCLUDED.user_id, currency = EXCLUDED.currency,
                           status = EXCLUDED.status, updated_at = now()
                       WHERE (account_directory.status, account_directory.currency)
                             IS DISTINCT FROM (EXCLUDED.status, EXCLUDED.currency)""",
                    [(r["iban"], r["user_id"], region, r["currency"], r["status"]) for r in rows])


async def recovery_loop() -> None:
    log.info(f"recovery loop ativo (a cada {settings.recovery_interval}s, presumed abort após "
             f"{logic.PREPARE_TIMEOUT_SECONDS}s)")
    while True:
        try:
            await recovery_pass()
            await retry_pending_settlements()
        except Exception as exc:
            log.warning(f"recovery pass falhou: {exc!r}")
        await asyncio.sleep(settings.recovery_interval)


# --- admin / health ---------------------------------------------------------------------

@app.post("/admin/chaos")
async def set_chaos(request: Request):
    """Signed by an api instance (only admins can reach it through the api)."""
    body = await request.body()
    ok, reason = check_signed_request(body, request.headers, TRUSTED)
    if not ok:
        await audit.write("ADULTERACAO_DETETADA", reason=reason, endpoint="/admin/chaos")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, reason)
    mode = json.loads(body).get("mode", {})
    if mode.get("off"):
        chaos.__init__(0, 0, False, False, None)
    else:
        chaos.pause_before_prepare = int(mode.get("pause_before_prepare", chaos.pause_before_prepare))
        chaos.pause_after_prepare = int(mode.get("pause_after_prepare", chaos.pause_after_prepare))
        chaos.crash_after_prepare = bool(mode.get("crash_after_prepare", chaos.crash_after_prepare))
        chaos.crash_after_decision = bool(mode.get("crash_after_decision", chaos.crash_after_decision))
        chaos.fail_participant = mode.get("fail_participant", chaos.fail_participant) or None
    log.warning(f"chaos alterado: {asdict(chaos)}")
    await audit.write("CHAOS", **asdict(chaos), by=json.loads(body).get("by"))
    return asdict(chaos)


@app.get("/admin/chaos")
async def get_chaos():
    return asdict(chaos)


@app.get("/health")
async def health():
    out = {"in_flight": sorted(in_flight), "chaos": asdict(chaos), "shard_failures": shard_failures}
    try:
        async with core.connection(timeout=3) as conn:
            await conn.execute("SELECT 1")
        out["log"] = "ok"
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, {**out, "log": repr(exc)})
    return out
