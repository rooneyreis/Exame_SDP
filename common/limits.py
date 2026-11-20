"""Limits per CLIENT, shared by the api (GET /me/limits, early checks) and the coordinator
(the authoritative check, under a per-client lock, when the transfer enters the log).

- max_transfer_amount: maximum per transfer, in EUR (converted from the source currency).
- daily_limit_eur:     sum of what a client sent TODAY from ALL their accounts, in EUR.
  Transfers between two accounts of the same client do not count (no money leaves them),
  and aborted ones do not count. Opening more accounts does not raise the limit.
"""
from decimal import ROUND_HALF_EVEN, Decimal

CENT = Decimal("0.01")
DEFAULTS = {
    "max_transfer_amount": Decimal("10000.00"),
    "approval_threshold": Decimal("5000.00"),
    "max_accounts_per_client": Decimal("5"),
    "daily_limit_eur": Decimal("50000.00"),
}

# EUR value of an amount, with the rate of fx_rates (pg-core / coordinator database).
EUR_RATE_SQL = "SELECT rate FROM fx_rates WHERE base = %s AND quote = 'EUR'"

# What the client already sent today, in EUR (transactions table, pg-core).
SENT_TODAY_SQL = """
  SELECT COALESCE(sum(amount_eur), 0) AS total, count(*) AS n
  FROM transactions
  WHERE user_id = %s AND NOT own_transfer AND state <> 'ABORTADA'
    AND created_at >= date_trunc('day', now())
"""


def to_eur(amount: Decimal, rate: Decimal | None) -> Decimal:
    """rate = units of EUR per unit of the source currency (1 for EUR)."""
    return (Decimal(amount) * (rate if rate is not None else Decimal(1))).quantize(CENT, rounding=ROUND_HALF_EVEN)


def daily_problem(sent_today_eur: Decimal, amount_eur: Decimal, limit_eur: Decimal) -> str | None:
    if sent_today_eur + amount_eur > limit_eur:
        return (f"limite diário do cliente excedido ({sent_today_eur + amount_eur:.2f} EUR > "
                f"{limit_eur:.2f} EUR, somando todas as contas)")
    return None


def max_problem(amount_eur: Decimal, max_eur: Decimal) -> str | None:
    if amount_eur > max_eur:
        return f"montante acima do máximo por transferência ({amount_eur:.2f} EUR > {max_eur:.2f} EUR)"
    return None
