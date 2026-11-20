"""Pure rules of the 2PC coordinator (no database, no HTTP): unit-tested.

Everything here is a decision; the code that talks to the databases is in main.py.
"""
from datetime import datetime, timezone
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from common.db import is_valid_iban, region_of_iban
from common.transfers import transfer_tx_id

MAX_AMOUNT = Decimal("10000.00")
CENT = Decimal("0.01")
PREPARE_TIMEOUT_SECONDS = 30      # PREPARANDO older than this (and not in flight) -> presumed abort
MAX_CLOCK_SKEW_SECONDS = 300      # signed requests older/newer than this are refused (anti-replay)
MAX_BACKOFF_SECONDS = 30

# Global lock order for distributed transactions: every transaction prepares EU before AM.
# Two transfers in opposite directions can never wait for each other in a cycle, so there
# is no distributed deadlock (which no single PostgreSQL could detect).
REGION_ORDER = ("EU", "AM")


def scoped_idempotency_key(user_id: str, idempotency_key: str) -> str:
    """Keys are per user: two clients may use the same key without colliding."""
    return f"{user_id}:{idempotency_key}"


def transfer_kind(from_region: str, to_region: str) -> str:
    return "LOCAL" if from_region == to_region else "DISTRIBUIDA"


def convert(amount: Decimal, rate: Decimal) -> Decimal:
    """Banker's rounding to cents (no systematic bias up or down)."""
    return (amount * rate).quantize(CENT, rounding=ROUND_HALF_EVEN)


def participants(from_iban: str, to_iban: str) -> list[tuple[str, str, str]]:
    """[(region, side, iban)] in the global lock order (by region, then by IBAN)."""
    legs = [(region_of_iban(from_iban), "DEBITO", from_iban), (region_of_iban(to_iban), "CREDITO", to_iban)]
    return sorted(legs, key=lambda leg: (REGION_ORDER.index(leg[0]), leg[2]))


def debit_problem(account: dict | None, amount: Decimal, debited_today: Decimal) -> str | None:
    if account is None:
        return "conta de origem não existe"
    if account["status"] != "ATIVA":
        return f"conta de origem {account['status']}"
    if account["balance"] < amount:
        return "saldo insuficiente"
    if debited_today + amount > account["daily_limit"]:
        return f"limite diário excedido ({debited_today + amount} > {account['daily_limit']})"
    return None


def credit_problem(account: dict | None) -> str | None:
    if account is None:
        return "conta de destino não existe"
    if account["status"] != "ATIVA":
        return f"conta de destino {account['status']}"
    return None


def payload_problem(payload: dict, now: datetime, max_amount: Decimal = MAX_AMOUNT) -> str | None:
    """Validates a signed transfer request (the signature itself was already checked)."""
    required = {"tx_id", "idempotency_key", "user_id", "from_iban", "to_iban", "amount", "ts"}
    if missing := required - payload.keys():
        return f"campos em falta: {sorted(missing)}"
    if not (is_valid_iban(payload["from_iban"]) and is_valid_iban(payload["to_iban"])):
        return "IBAN inválido"
    if payload["from_iban"] == payload["to_iban"]:
        return "origem e destino iguais"
    try:
        amount = Decimal(payload["amount"])
    except (InvalidOperation, TypeError):
        return "montante inválido"
    if amount <= 0 or amount > max_amount or amount != amount.quantize(CENT):
        return f"montante fora dos limites (0 < montante <= {max_amount}, 2 casas decimais)"
    if str(transfer_tx_id(payload["user_id"], payload["idempotency_key"])) != payload["tx_id"]:
        return "tx_id não corresponde à Idempotency-Key"
    try:
        ts = datetime.fromisoformat(payload["ts"])
    except ValueError:
        return "ts inválido"
    if abs((now - ts).total_seconds()) > MAX_CLOCK_SKEW_SECONDS:
        return "pedido fora da janela temporal (possível replay)"
    return None


# --- Recovery (presumed abort) -------------------------------------------------------

def recovery_action(state: str, kind: str, age_seconds: float) -> str:
    """What the recovery loop does with an unfinished transaction that is NOT in flight.

    DECISAO_COMMIT -> COMMIT      the decision is durable: it must be carried out
    PREPARANDO     -> ABORT       no decision after 30 s: presumed abort
    INICIADA       -> ABORT / CHECK_LOCAL (a LOCAL tx may have committed before the crash)
    otherwise      -> WAIT
    """
    if state == "DECISAO_COMMIT":
        return "COMMIT"
    if age_seconds <= PREPARE_TIMEOUT_SECONDS:
        return "WAIT"
    if state == "PREPARANDO":
        return "ABORT"
    if state == "INICIADA":
        return "CHECK_LOCAL" if kind == "LOCAL" else "ABORT"
    return "WAIT"


def orphan_action(state: str | None, age_seconds: float | None) -> str:
    """A prepared transaction found in a shard (pg_prepared_xacts) that the main pass did
    not handle. Decided by what the coordinator log says about it."""
    if state in ("CONFIRMADA", "DECISAO_COMMIT"):
        return "COMMIT"
    if state is None or state in ("ABORTADA", "INICIADA"):
        return "ROLLBACK"           # unknown to the log or never decided: presumed abort
    if state == "PREPARANDO" and age_seconds is not None and age_seconds > PREPARE_TIMEOUT_SECONDS:
        return "ROLLBACK"
    return "SKIP"


def backoff_seconds(failures: int) -> int:
    return min(MAX_BACKOFF_SECONDS, 2 ** max(failures - 1, 0)) if failures else 0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
