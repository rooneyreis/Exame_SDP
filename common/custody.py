"""Custódia de créditos para uma região totalmente indisponível.

Quando uma região está em baixo (primário E réplica inacessíveis), uma operação destinada a
uma conta dessa região não é recusada: é executada noutro shard ativo, numa "conta de
custódia" com o IBAN da conta de destino (tabelas custody_accounts / custody_movements).

- Crédito (transferência recebida, depósito): fica em custódia no shard que já guarda valor
  para essa conta; se nenhum guarda, no primeiro shard ativo pela ordem global.
- Débito (o titular usa o valor retido: transferência, levantamento): sai do shard que tem
  valor retido suficiente.
- Quando a região volta, o coordenador reencaminha o saldo restante e o histórico (os
  movimentos feitos em custódia aparecem no extrato da conta, com o nó onde aconteceram).

As regras de decisão são funções puras (testadas em tests/unit/test_custody.py); as
operações SQL recebem uma ligação já dentro de uma transação.
"""
from dataclasses import dataclass
from decimal import Decimal

from .db import REGIONS, region_of_iban

# Mesma ordem global do 2PC (logic.REGION_ORDER): escolha determinística do shard.
ORDER = ("EU", "AM", "AF")


class CustodyError(Exception):
    """A operação em custódia não é possível (sem valor retido, saldo insuficiente...)."""


# --- decisões (puras) ---------------------------------------------------------------------

def _ordered(regions) -> list[str]:
    return sorted(regions, key=ORDER.index)


def credit_holder(target_region: str, reachable: list[str], holding: dict[str, Decimal]) -> str | None:
    """Shard onde fica um crédito para uma conta da região `target_region` (em baixo).
    reachable: shards ativos; holding: {shard: saldo retido} dos que já guardam valor
    para esta conta. Prefere juntar ao valor já retido (um só sítio para o titular usar)."""
    candidates = [r for r in _ordered(reachable) if r != target_region]
    for r in candidates:
        if r in holding:
            return r
    return candidates[0] if candidates else None


def debit_holder(holding: dict[str, Decimal], amount: Decimal) -> str | None:
    """Shard de onde sai um débito do valor retido: o primeiro com saldo suficiente; se
    nenhum chega, o primeiro que tem valor (a operação falha com "saldo insuficiente")."""
    regions = _ordered(holding)
    for r in regions:
        if holding[r] >= amount:
            return r
    return regions[0] if regions else None


@dataclass
class Replayed:
    move: dict
    balance_after: Decimal


def replay(start_balance: Decimal, moves: list[dict]) -> tuple[list[Replayed], Decimal]:
    """Aplica o histórico da custódia (por ordem) ao saldo real da conta de destino.
    Devolve cada movimento com o novo saldo_após e o saldo final. O saldo nunca fica
    negativo: a custódia nunca gastou mais do que tinha recebido."""
    balance = start_balance
    out = []
    for m in moves:
        balance += m["amount"] if m["type"] == "CREDITO" else -m["amount"]
        if balance < 0:
            raise CustodyError(f"histórico inconsistente: saldo negativo no movimento {m.get('id')}")
        out.append(Replayed(m, balance))
    return out, balance


def net_of(moves: list[dict]) -> Decimal:
    return sum((m["amount"] if m["type"] == "CREDITO" else -m["amount"] for m in moves), Decimal(0))


# --- SQL (dentro de uma transação já aberta) ---------------------------------------------

async def holdings(conn, iban: str) -> Decimal | None:
    row = await (await conn.execute(
        "SELECT balance FROM custody_accounts WHERE target_iban = %s", (iban,))).fetchone()
    return None if row is None else row["balance"]


async def apply(conn, *, iban: str, user_id, currency: str, side: str, amount: Decimal, tx_id,
                origin: str, counterparty: str | None) -> Decimal:
    """Um débito ou crédito na conta de custódia de `iban` (bloqueada com FOR UPDATE até ao
    fim da transação). Devolve o novo saldo retido."""
    if side == "CREDITO":
        await conn.execute(
            """INSERT INTO custody_accounts (target_iban, target_region, user_id, currency)
               VALUES (%s, %s, %s, %s) ON CONFLICT (target_iban) DO NOTHING""",
            (iban, region_of_iban(iban), user_id, currency))
    row = await (await conn.execute(
        "SELECT * FROM custody_accounts WHERE target_iban = %s FOR UPDATE", (iban,))).fetchone()
    if row is None:
        raise CustodyError("sem valor retido para esta conta")
    if row["currency"] != currency:
        raise CustodyError(f"moeda diferente da custódia ({row['currency']})")
    new_balance = row["balance"] + (amount if side == "CREDITO" else -amount)
    if new_balance < 0:
        raise CustodyError(f"saldo insuficiente no valor retido ({row['balance']:.2f} {currency})")
    await conn.execute("UPDATE custody_accounts SET balance = %s, updated_at = now() WHERE target_iban = %s",
                       (new_balance, iban))
    await conn.execute(
        """INSERT INTO custody_movements (target_iban, tx_id, type, amount, currency, balance_after, origin, counterparty)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (iban, tx_id, side, amount, currency, new_balance, origin, counterparty))
    return new_balance


def other_regions(region: str) -> list[str]:
    return [r for r in _ordered(REGIONS) if r != region]
