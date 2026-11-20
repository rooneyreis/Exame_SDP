"""Back-office: transferências registadas por operadores (com aprovação), limites,
gestão de contas, consultas globais, visão financeira e auditoria.

Cada endpoint declara a permissão de que precisa (common/rbac.py), verificada no servidor.
Nada aqui apaga registos financeiros (a base de dados nem concede DELETE à API).
"""
import asyncio
import json
import os
import time
import uuid
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from common import limits
from common.audit import verify_chain
from common.db import REGIONS, is_valid_iban, region_of_iban
from common.transfers import transfer_tx_id

from .main import (account_out, core, eur_value, load_account, log, record, require_permission, settings, shards,
                   signed_post)
from .schemas import AccountUpdate, Decision, SettingsUpdate, TransferRequestIn

router = APIRouter()


def jsonable(row: dict) -> dict:
    return {k: (str(v) if isinstance(v, (uuid.UUID, Decimal)) else v) for k, v in row.items()}


# --- limites institucionais ---------------------------------------------------------------

async def current_settings(fresh: bool = True) -> dict:
    """Lidos da tabela settings em CADA operação: com duas instâncias da api atrás do nginx,
    uma cache local deixaria uma delas a aplicar o limite antigo depois de o admin o mudar."""
    async with core.connection() as conn:
        rows = await (await conn.execute("SELECT key, value FROM settings")).fetchall()
    values = dict(limits.DEFAULTS)
    values.update({r["key"]: r["value"] for r in rows})
    return values


@router.get("/admin/settings")
async def get_settings(claims: dict = Depends(require_permission("settings:read"))):
    async with core.connection() as conn:
        rows = await (await conn.execute("SELECT * FROM settings ORDER BY key")).fetchall()
    return [jsonable(r) for r in rows]


@router.put("/admin/settings")
async def put_settings(body: SettingsUpdate, request: Request,
                       claims: dict = Depends(require_permission("settings:manage"))):
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "nada para alterar")
    old = await current_settings(fresh=True)
    new = {**old, **changes}
    if new["approval_threshold"] > new["max_transfer_amount"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "o limiar de aprovação não pode ser superior ao máximo por transferência")
    async with core.connection() as conn:
        for key, value in changes.items():
            await conn.execute("UPDATE settings SET value = %s, updated_by = %s, updated_at = now() WHERE key = %s",
                               (value, claims["sub"], key))
    await record("LIMITES_ALTERADOS", claims, request,
                 before={k: str(old[k]) for k in changes}, after={k: str(v) for k, v in changes.items()})
    return await get_settings(claims)


# --- pedidos de transferência (operador → aprovação do administrador) ------------------------

REQUEST_VIEW = """
  SELECT r.*, t.state AS tx_state, t.failure_reason, t.kind, t.converted_amount, t.to_currency,
         t.settlement_status,
         CASE WHEN t.state = 'CONFIRMADA' THEN 'EXECUTADA'
              WHEN t.state = 'ABORTADA' THEN 'FALHADA'
              ELSE r.status END AS effective_status
  FROM transfer_requests r LEFT JOIN transactions t ON t.tx_id = r.tx_id
"""


async def load_request(request_id) -> dict:
    async with core.connection() as conn:
        row = await (await conn.execute(REQUEST_VIEW + " WHERE r.id = %s", (request_id,))).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pedido não encontrado")
    return row


async def execute(req: dict, approver: str | None) -> dict:
    """Envia o pedido ao coordenador (2PC) com uma Idempotency-Key derivada do pedido:
    aprovar duas vezes, ou repetir após uma falha de rede, nunca executa duas vezes."""
    key = f"req-{req['id']}"
    tx_id = transfer_tx_id(str(req["owner_id"]), key)
    async with core.connection() as conn:
        await conn.execute("UPDATE transfer_requests SET status = 'EM_EXECUCAO', tx_id = %s, updated_at = now() "
                           "WHERE id = %s", (tx_id, req["id"]))
    payload = {
        "tx_id": str(tx_id), "idempotency_key": key, "user_id": str(req["owner_id"]),
        "from_iban": req["from_iban"], "to_iban": req["to_iban"], "amount": f"{req['amount']:.2f}",
        "ts": datetime.now(timezone.utc).isoformat(), "requested_by": settings.instance_id,
        "initiated_by": str(req["created_by"]), "initiated_role": req["created_by_role"],
        "approved_by": approver, "request_id": str(req["id"]),
    }
    try:
        response = await signed_post("/tx", payload)
        tx = response.json()
    except httpx.HTTPError as exc:
        log.warning(f"coordenador indisponível ao executar pedido {req['id']}: {exc!r}")
        return {"state": "INDISPONIVEL", "tx_id": str(tx_id)}
    final = {"CONFIRMADA": "EXECUTADA", "ABORTADA": "FALHADA"}.get(tx.get("state"))
    if final:
        async with core.connection() as conn:
            await conn.execute("UPDATE transfer_requests SET status = %s, updated_at = now() WHERE id = %s",
                               (final, req["id"]))
    return tx


@router.post("/transfer-requests", status_code=status.HTTP_201_CREATED)
async def create_request(body: TransferRequestIn, request: Request,
                         claims: dict = Depends(require_permission("transfer_requests:create"))):
    if body.from_iban == body.to_iban:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "origem e destino iguais")
    conf = await current_settings()
    source = await load_account(body.from_iban)
    if problem := limits.max_problem(await eur_value(body.amount, source["currency"]), conf["max_transfer_amount"]):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    await load_account(body.to_iban)                      # 404 se o destino não existir
    if source["status"] != "ATIVA":
        raise HTTPException(status.HTTP_409_CONFLICT, "conta de origem bloqueada")
    if body.amount > source["balance"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "saldo insuficiente na conta de origem")

    requires_approval = body.amount >= conf["approval_threshold"]
    rid = uuid.uuid4()
    async with core.connection() as conn:
        await conn.execute(
            """INSERT INTO transfer_requests (id, created_by, created_by_role, owner_id, from_iban, to_iban, amount,
                   currency, beneficiary_name, description, status, requires_approval, client_ip)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (rid, claims["sub"], claims["role"], source["user_id"], body.from_iban, body.to_iban, body.amount,
             source["currency"], body.beneficiary_name, body.description,
             "PENDENTE_APROVACAO" if requires_approval else "EM_EXECUCAO", requires_approval,
             request.client.host if request.client else None))
    req = await load_request(rid)
    await record("PEDIDO_TRANSFERENCIA_REGISTADO", claims, request, request_id=str(rid),
                 after={"from_iban": body.from_iban, "to_iban": body.to_iban, "amount": f"{body.amount:.2f}",
                        "requires_approval": requires_approval})
    tx = None
    if not requires_approval:
        tx = await execute(req, approver=None)
        req = await load_request(rid)
    return {"request": jsonable(req), "transaction": tx,
            "message": "aguarda aprovação de um administrador" if requires_approval else "submetida para processamento"}


@router.get("/transfer-requests")
async def list_requests(status_filter: str | None = Query(None, alias="status"), mine: bool = False,
                        limit: int = Query(100, ge=1, le=500),
                        claims: dict = Depends(require_permission("transfer_requests:read"))):
    where, args = [], []
    if mine:
        where.append("r.created_by = %s"); args.append(claims["sub"])
    query = REQUEST_VIEW + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY r.created_at DESC LIMIT %s"
    async with core.connection() as conn:
        rows = await (await conn.execute(query, [*args, limit])).fetchall()
    if status_filter:
        rows = [r for r in rows if r["effective_status"] == status_filter]
    return [jsonable(r) for r in rows]


@router.get("/transfer-requests/{request_id}")
async def get_request(request_id: uuid.UUID, claims: dict = Depends(require_permission("transfer_requests:read"))):
    return jsonable(await load_request(request_id))


@router.post("/transfer-requests/{request_id}/approve")
async def approve_request(request_id: uuid.UUID, request: Request, body: Decision | None = None,
                          claims: dict = Depends(require_permission("transfer_requests:decide"))):
    async with core.connection() as conn:
        # Transição atómica: só um administrador consegue aprovar, e nunca quem o registou.
        row = await (await conn.execute(
            """UPDATE transfer_requests SET decided_by = %s, decided_at = now(), decision_reason = %s,
                   status = 'EM_EXECUCAO', updated_at = now()
               WHERE id = %s AND status = 'PENDENTE_APROVACAO' AND created_by <> %s RETURNING *""",
            (claims["sub"], body.reason if body else None, request_id, claims["sub"]))).fetchone()
    if row is None:
        req = await load_request(request_id)
        if str(req["created_by"]) == claims["sub"]:
            await record("PEDIDO_TRANSFERENCIA_APROVADO", claims, request, result="NEGADO", request_id=str(request_id),
                         reason="segregação de funções: quem regista não aprova")
            raise HTTPException(status.HTTP_403_FORBIDDEN, "quem registou o pedido não o pode aprovar")
        raise HTTPException(status.HTTP_409_CONFLICT, f"o pedido já não está pendente (estado: {req['effective_status']})")
    await record("PEDIDO_TRANSFERENCIA_APROVADO", claims, request, request_id=str(request_id),
                 before={"status": "PENDENTE_APROVACAO"}, after={"status": "EM_EXECUCAO"})
    tx = await execute(row, approver=claims["sub"])
    return {"request": jsonable(await load_request(request_id)), "transaction": tx}


@router.post("/transfer-requests/{request_id}/reject")
async def reject_request(request_id: uuid.UUID, body: Decision, request: Request,
                         claims: dict = Depends(require_permission("transfer_requests:decide"))):
    if not body.reason or len(body.reason.strip()) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "indique o motivo da rejeição")
    async with core.connection() as conn:
        row = await (await conn.execute(
            """UPDATE transfer_requests SET decided_by = %s, decided_at = now(), decision_reason = %s,
                   status = 'REJEITADA', updated_at = now()
               WHERE id = %s AND status = 'PENDENTE_APROVACAO' RETURNING *""",
            (claims["sub"], body.reason.strip(), request_id))).fetchone()
    if row is None:
        req = await load_request(request_id)
        raise HTTPException(status.HTTP_409_CONFLICT, f"o pedido já não está pendente (estado: {req['effective_status']})")
    await record("PEDIDO_TRANSFERENCIA_REJEITADO", claims, request, request_id=str(request_id), reason=body.reason,
                 before={"status": "PENDENTE_APROVACAO"}, after={"status": "REJEITADA"})
    return jsonable(await load_request(request_id))


# --- consultas globais -------------------------------------------------------------------

@router.get("/admin/transfers")
async def all_transfers(state: str | None = None, kind: str | None = None, q: str | None = Query(None, max_length=80),
                        initiated_role: str | None = None, date_from: date_cls | None = None,
                        date_to: date_cls | None = None, limit: int = Query(100, ge=1, le=1000),
                        offset: int = Query(0, ge=0),
                        claims: dict = Depends(require_permission("transfers:read:any"))):
    where, args = ["true"], []
    if state:
        where.append("state = %s"); args.append(state)
    if kind:
        where.append("kind = %s"); args.append(kind)
    if initiated_role:
        where.append("coalesce(initiated_role, 'cliente') = %s"); args.append(initiated_role)
    if q:
        where.append("(from_iban ILIKE %s OR to_iban ILIKE %s OR tx_id::text ILIKE %s)"); args += [f"%{q}%"] * 3
    if date_from:
        where.append("created_at >= %s"); args.append(date_from)
    if date_to:
        where.append("created_at < %s"); args.append(date_to + timedelta(days=1))
    cond = " AND ".join(where)
    async with core.connection() as conn:
        total = (await (await conn.execute(f"SELECT count(*) AS n FROM transactions WHERE {cond}", args)).fetchone())["n"]
        rows = await (await conn.execute(
            f"""SELECT tx_id, user_id, from_iban, to_iban, from_region, to_region, amount, from_currency,
                       to_currency, fx_rate, converted_amount, kind, state, failure_reason, settlement_status,
                       coalesce(initiated_by, user_id) AS initiated_by, coalesce(initiated_role, 'cliente') AS initiated_role,
                       approved_by, request_id, request_sha256, created_at, updated_at
                FROM transactions WHERE {cond} ORDER BY created_at DESC LIMIT %s OFFSET %s""",
            [*args, limit, offset])).fetchall()
    return {"total": total, "items": [jsonable(r) for r in rows]}


@router.get("/admin/accounts")
async def all_accounts(region: str | None = None, status_filter: str | None = Query(None, alias="status"),
                       q: str | None = Query(None, max_length=40),
                       claims: dict = Depends(require_permission("accounts:read:any"))):
    regions = [region] if region in REGIONS else list(REGIONS)

    async def fetch(r):
        async with shards.for_region(r, read=True).connection() as conn:
            return await (await conn.execute("SELECT * FROM accounts ORDER BY iban")).fetchall()
    rows = [a for part in await asyncio.gather(*(fetch(r) for r in regions)) for a in part]
    if status_filter:
        rows = [a for a in rows if a["status"] == status_filter]
    if q:
        rows = [a for a in rows if q.upper() in a["iban"] or q.lower() in str(a["user_id"])]
    return [account_out(a) for a in rows]


@router.patch("/admin/accounts/{iban}")
async def update_account(iban: str, body: AccountUpdate, request: Request,
                         claims: dict = Depends(require_permission("accounts:manage"))):
    if not is_valid_iban(iban):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "IBAN inválido")
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "nada para alterar")
    async with shards.for_iban(iban).connection() as conn:
        async with conn.transaction():
            old = await (await conn.execute("SELECT * FROM accounts WHERE iban = %s FOR UPDATE", (iban,))).fetchone()
            if old is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "conta não encontrada")
            if old["status"] == "ENCERRADA":
                raise HTTPException(status.HTTP_409_CONFLICT, "a conta está encerrada")
            sets = ", ".join(f"{k} = %s" for k in changes)
            new = await (await conn.execute(f"UPDATE accounts SET {sets} WHERE iban = %s RETURNING *",
                                            [*changes.values(), iban])).fetchone()
    await record("CONTA_ALTERADA", claims, request, iban=iban,
                 before={k: str(old[k]) for k in changes}, after={k: str(v) for k, v in changes.items()})
    return account_out(new)


# --- visão financeira ----------------------------------------------------------------------

@router.get("/admin/overview")
async def overview(days: int = Query(14, ge=1, le=90), claims: dict = Depends(require_permission("reports:read"))):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with core.connection() as conn:
        by_state = await (await conn.execute("SELECT state, kind, count(*) AS n FROM transactions GROUP BY 1, 2")).fetchall()
        daily = await (await conn.execute(
            """SELECT date_trunc('day', created_at) AS day, from_currency AS currency,
                      count(*) FILTER (WHERE state = 'CONFIRMADA') AS confirmed,
                      count(*) FILTER (WHERE state = 'ABORTADA') AS failed,
                      coalesce(sum(amount) FILTER (WHERE state = 'CONFIRMADA'), 0) AS volume
               FROM transactions WHERE created_at >= %s GROUP BY 1, 2 ORDER BY 1""", (since,))).fetchall()
        last24 = (await (await conn.execute(
            """SELECT count(*) AS n, count(*) FILTER (WHERE state = 'ABORTADA') AS failed,
                      count(*) FILTER (WHERE state NOT IN ('CONFIRMADA','ABORTADA')) AS in_progress
               FROM transactions WHERE created_at >= now() - interval '24 hours'""")).fetchone())
        pending = (await (await conn.execute(
            "SELECT count(*) AS n, coalesce(sum(amount), 0) AS amount FROM transfer_requests WHERE status = 'PENDENTE_APROVACAO'"
        )).fetchone())
        settlement = await (await conn.execute(
            "SELECT settlement_status, count(*) AS n FROM transactions GROUP BY 1")).fetchall()

    async def balances(r):
        async with shards.for_region(r, read=True).connection() as conn:
            return await (await conn.execute(
                """SELECT currency, count(*) AS accounts, sum(balance) AS total,
                          count(*) FILTER (WHERE status = 'BLOQUEADA') AS blocked FROM accounts GROUP BY currency""")).fetchall()
    per_region = dict(zip(REGIONS, await asyncio.gather(*(balances(r) for r in REGIONS))))
    return {
        "transactions": [jsonable(r) for r in by_state],
        "daily": [jsonable(r) for r in daily],
        "last_24h": jsonable(last24),
        "pending_approvals": jsonable(pending),
        "settlement": [jsonable(r) for r in settlement],
        "balances": {r: [jsonable(x) for x in rows] for r, rows in per_region.items()},
        "limits": {k: str(v) for k, v in (await current_settings()).items()},
    }


# --- fiscalização: transações suspeitas e falhas ---------------------------------------------

@router.get("/admin/suspicious")
async def suspicious(days: int = Query(30, ge=1, le=365), claims: dict = Depends(require_permission("audit:read"))):
    """Regras explícitas (sem dados simulados), aplicadas aos registos reais do coordenador."""
    limits = await current_settings()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    findings = []
    async with core.connection() as conn:
        async def q(sql, args=()):
            return await (await conn.execute(sql, args)).fetchall()

        for r in await q("""SELECT tx_id, from_iban, to_iban, amount, from_currency, created_at FROM transactions
                            WHERE state = 'CONFIRMADA' AND amount >= %s AND created_at >= %s""",
                         (limits["max_transfer_amount"] * Decimal("0.8"), since)):
            findings.append({"rule": "VALOR_ELEVADO", "severity": "media", "tx_id": str(r["tx_id"]), "at": r["created_at"],
                             "detail": f"{r['amount']} {r['from_currency']} (≥ 80% do máximo) de {r['from_iban']} para {r['to_iban']}"})
        for r in await q("""SELECT from_iban, max(n) AS n, max(created_at) AS at FROM (
                              SELECT from_iban, created_at, count(*) OVER (PARTITION BY from_iban ORDER BY created_at
                                     RANGE BETWEEN interval '10 minutes' PRECEDING AND CURRENT ROW) AS n
                              FROM transactions WHERE created_at >= %s) w
                            WHERE n >= 5 GROUP BY from_iban""", (since,)):
            findings.append({"rule": "VELOCIDADE", "severity": "media", "iban": r["from_iban"], "at": r["at"],
                             "detail": f"{r['n']} transferências em 10 minutos a partir de {r['from_iban']}"})
        for r in await q("""SELECT from_iban, count(*) AS n, max(created_at) AS at FROM transactions
                            WHERE state = 'ABORTADA' AND created_at >= now() - interval '24 hours'
                            GROUP BY from_iban HAVING count(*) >= 3""", ()):
            findings.append({"rule": "FALHAS_REPETIDAS", "severity": "media", "iban": r["from_iban"], "at": r["at"],
                             "detail": f"{r['n']} transferências falhadas nas últimas 24 h"})
        for r in await q("""SELECT tx_id, amount, from_currency, converted_amount, to_currency, updated_at FROM transactions
                            WHERE settlement_status = 'REJEITADA' AND created_at >= %s""", (since,)):
            findings.append({"rule": "LIQUIDACAO_REJEITADA", "severity": "alta", "tx_id": str(r["tx_id"]), "at": r["updated_at"],
                             "detail": f"banco correspondente rejeitou {r['converted_amount']} {r['to_currency']}"})
        for r in await q("""SELECT tx_id, amount, from_currency, created_at FROM transactions
                            WHERE initiated_role = 'operador' AND amount >= %s AND approved_by IS NULL""",
                         (limits["approval_threshold"],)):
            findings.append({"rule": "SEM_APROVACAO", "severity": "alta", "tx_id": str(r["tx_id"]), "at": r["created_at"],
                             "detail": f"{r['amount']} {r['from_currency']} registada por operador acima do limiar sem aprovação"})
        for r in await q("""SELECT tx_id, state, created_at FROM transactions
                            WHERE state NOT IN ('CONFIRMADA','ABORTADA') AND updated_at < now() - interval '5 minutes'""", ()):
            findings.append({"rule": "PENDENTE_HA_MUITO", "severity": "alta", "tx_id": str(r["tx_id"]), "at": r["created_at"],
                             "detail": f"transação em {r['state']} há mais de 5 minutos"})
        for r in await q("""SELECT t.tx_id, t.state, max(e.at) AS at, string_agg(DISTINCT e.event, ', ') AS events
                            FROM tx_events e JOIN transactions t USING (tx_id)
                            WHERE (e.event LIKE 'RECUPERACAO_%%' OR e.event LIKE 'ALERTA_%%' OR e.event LIKE 'ORFA_%%'
                                   OR e.event LIKE 'COMMIT_PENDENTE_%%' OR e.event LIKE 'LIQUIDACAO_ACK_INVALIDO')
                              AND e.at >= %s GROUP BY t.tx_id, t.state""", (since,)):
            findings.append({"rule": "FALHA_DE_PROCESSAMENTO", "severity": "baixa", "tx_id": str(r["tx_id"]), "at": r["at"],
                             "detail": f"recuperação automática ({r['events']}); estado final {r['state']}"})
        failures = await q("""SELECT tx_id, from_iban, to_iban, amount, from_currency, failure_reason, created_at
                              FROM transactions WHERE state = 'ABORTADA' AND created_at >= %s
                              ORDER BY created_at DESC LIMIT 200""", (since,))
    findings.sort(key=lambda f: f["at"], reverse=True)
    return {"findings": findings, "failures": [jsonable(r) for r in failures],
            "rules": {"VALOR_ELEVADO": "≥ 80% do máximo por transferência", "VELOCIDADE": "≥ 5 transferências da mesma conta em 10 min",
                      "FALHAS_REPETIDAS": "≥ 3 falhadas da mesma conta em 24 h", "LIQUIDACAO_REJEITADA": "rejeitada pelo banco correspondente",
                      "SEM_APROVACAO": "operador acima do limiar sem aprovação registada",
                      "PENDENTE_HA_MUITO": "estado intermédio há mais de 5 minutos",
                      "FALHA_DE_PROCESSAMENTO": "concluída por recuperação automática do 2PC"}}


# --- registo de auditoria pesquisável ------------------------------------------------------

@router.get("/admin/audit/events")
async def audit_events(date: date_cls | None = None, action: str | None = None, actor: str | None = None,
                       result: str | None = None, q: str | None = Query(None, max_length=80),
                       limit: int = Query(300, ge=1, le=2000),
                       claims: dict = Depends(require_permission("audit:read"))):
    """Eventos de todos os nós (auditoria encadeada no NFS), com a validação da cadeia de cada ficheiro."""
    day = (date or datetime.now(timezone.utc).date()).isoformat()

    def read() -> tuple[list, dict]:
        folder = os.path.join(settings.audit_dir, day)
        events, chains = [], {}
        if not os.path.isdir(folder):
            return events, chains
        for name in sorted(os.listdir(folder)):
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                lines = [l for l in f.read().splitlines() if l.strip()]
            ok, bad, reason = verify_chain(lines)
            chains[name] = {"ok": ok, "first_bad_line": bad, "lines": len(lines)}
            for n, raw in enumerate(lines, start=1):
                try:
                    e = json.loads(raw)
                except ValueError:
                    continue
                e["_file"], e["_line"] = name, n
                e["_tampered"] = bad is not None and n >= bad
                events.append(e)
        return events, chains

    events, chains = await asyncio.to_thread(read)
    actions = sorted({e.get("event") for e in events if e.get("event")})
    if action:
        events = [e for e in events if e.get("event") == action]
    if actor:
        events = [e for e in events if e.get("actor") == actor or e.get("by") == actor]
    if result:
        events = [e for e in events if e.get("result") == result]
    if q:
        events = [e for e in events if q.lower() in json.dumps(e, ensure_ascii=False).lower()]
    events.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return {"date": day, "total": len(events), "chains": chains, "actions": actions, "items": events[:limit]}
