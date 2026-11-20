"""Pure rules of the 2PC coordinator (services/coordinator/coordinator_service/logic.py)."""
from datetime import timedelta
from decimal import Decimal

import pytest

from common.transfers import transfer_tx_id
from coordinator_service import logic as L

NOW = L.utcnow()


def payload(**overrides):
    p = {"idempotency_key": "k1", "user_id": "u1", "from_iban": "GS-EU-00000001", "to_iban": "GS-AM-00000002",
         "amount": "100.00", "ts": NOW.isoformat()}
    p["tx_id"] = str(transfer_tx_id(p["user_id"], p["idempotency_key"]))
    p.update(overrides)
    return p


# ---------- exchange ----------

@pytest.mark.parametrize("amount,rate,expected", [
    ("100.00", "1.08000000", "108.00"),
    ("100.00", "0.92592593", "92.59"),
    ("0.05", "1.10000000", "0.06"),      # 0.055 -> banker's rounding to even -> 0.06
    ("0.25", "0.10000000", "0.02"),      # 0.025 -> 0.02 (round half to even)
    ("10000.00", "70.50000000", "705000.00"),
])
def test_convert_rounds_to_cents_half_even(amount, rate, expected):
    assert L.convert(Decimal(amount), Decimal(rate)) == Decimal(expected)


# ---------- kind / ordering ----------

def test_kind():
    assert L.transfer_kind("EU", "EU") == "LOCAL"
    assert L.transfer_kind("EU", "AM") == "DISTRIBUIDA"


def test_participants_always_prepare_europe_first():
    """Global lock order: both directions lock EU before AM -> no distributed deadlock."""
    assert [p[0] for p in L.participants("GS-EU-00000001", "GS-AM-00000001")] == ["EU", "AM"]
    assert [p[0] for p in L.participants("GS-AM-00000001", "GS-EU-00000001")] == ["EU", "AM"]
    assert L.participants("GS-AM-00000001", "GS-EU-00000001")[0][1] == "CREDITO"


def test_local_legs_are_ordered_by_iban():
    a = L.participants("GS-EU-00000002", "GS-EU-00000001")
    b = L.participants("GS-EU-00000001", "GS-EU-00000002")
    assert [leg[2] for leg in a] == [leg[2] for leg in b] == ["GS-EU-00000001", "GS-EU-00000002"]


# ---------- participant checks ----------

ACC = {"status": "ATIVA", "balance": Decimal("500.00"), "daily_limit": Decimal("1000.00")}


def test_debit_ok():
    assert L.debit_problem(ACC, Decimal("100"), Decimal("0")) is None


@pytest.mark.parametrize("account,amount,today,msg", [
    (None, "1", "0", "não existe"),
    ({**ACC, "status": "BLOQUEADA"}, "1", "0", "BLOQUEADA"),
    (ACC, "500.01", "0", "saldo insuficiente"),
    (ACC, "100", "950", "limite diário"),
])
def test_debit_problems(account, amount, today, msg):
    assert msg in L.debit_problem(account, Decimal(amount), Decimal(today))


def test_credit_problems():
    assert L.credit_problem(ACC) is None
    assert "não existe" in L.credit_problem(None)
    assert "BLOQUEADA" in L.credit_problem({**ACC, "status": "BLOQUEADA"})


# ---------- signed payload ----------

def test_valid_payload():
    assert L.payload_problem(payload(), NOW) is None


@pytest.mark.parametrize("overrides,msg", [
    ({"amount": "0"}, "fora dos limites"),
    ({"amount": "10000.01"}, "fora dos limites"),
    ({"amount": "1.001"}, "fora dos limites"),
    ({"amount": "abc"}, "montante inválido"),
    ({"to_iban": "GS-EU-00000001"}, "iguais"),
    ({"from_iban": "XX"}, "IBAN inválido"),
    ({"tx_id": "00000000-0000-0000-0000-000000000000"}, "tx_id"),
    ({"ts": (NOW - timedelta(minutes=10)).isoformat()}, "replay"),
])
def test_payload_problems(overrides, msg):
    assert msg in L.payload_problem(payload(**overrides), NOW)


def test_missing_fields():
    p = payload()
    del p["amount"]
    assert "em falta" in L.payload_problem(p, NOW)


def test_tx_id_is_deterministic_and_scoped_per_user():
    assert transfer_tx_id("u1", "k") == transfer_tx_id("u1", "k")
    assert transfer_tx_id("u1", "k") != transfer_tx_id("u2", "k")
    assert L.scoped_idempotency_key("u1", "k") != L.scoped_idempotency_key("u2", "k")


# ---------- recovery ----------

@pytest.mark.parametrize("state,kind,age,action", [
    ("DECISAO_COMMIT", "DISTRIBUIDA", 1, "COMMIT"),      # decision exists: commit, whatever the age
    ("DECISAO_COMMIT", "DISTRIBUIDA", 999, "COMMIT"),
    ("PREPARANDO", "DISTRIBUIDA", 10, "WAIT"),           # maybe still running somewhere: wait
    ("PREPARANDO", "DISTRIBUIDA", 31, "ABORT"),          # presumed abort
    ("INICIADA", "DISTRIBUIDA", 31, "ABORT"),
    ("INICIADA", "LOCAL", 31, "CHECK_LOCAL"),            # local commit may have happened before the crash
    ("INICIADA", "LOCAL", 5, "WAIT"),
])
def test_recovery_action(state, kind, age, action):
    assert L.recovery_action(state, kind, age) == action


@pytest.mark.parametrize("state,age,action", [
    ("CONFIRMADA", 1, "COMMIT"), ("DECISAO_COMMIT", 1, "COMMIT"),
    (None, None, "ROLLBACK"), ("ABORTADA", 1, "ROLLBACK"), ("INICIADA", 1, "ROLLBACK"),
    ("PREPARANDO", 5, "SKIP"), ("PREPARANDO", 60, "ROLLBACK"),
])
def test_orphan_action(state, age, action):
    assert L.orphan_action(state, age) == action


def test_backoff_is_exponential_and_capped():
    assert [L.backoff_seconds(n) for n in range(0, 8)] == [0, 1, 2, 4, 8, 16, 30, 30]


# ---------- região África ----------

def test_region_order_includes_africa_last():
    assert L.REGION_ORDER == ("EU", "AM", "AF")


@pytest.mark.parametrize("src,dst", [("GS-AF-00000001", "GS-EU-00000001"), ("GS-EU-00000001", "GS-AF-00000001"),
                                     ("GS-AF-00000001", "GS-AM-00000001"), ("GS-AM-00000001", "GS-AF-00000001")])
def test_participants_follow_the_global_order_with_africa(src, dst):
    order = [p[0] for p in L.participants(src, dst)]
    assert order == sorted(order, key=L.REGION_ORDER.index)


def test_local_africa_transfer_is_local():
    assert L.transfer_kind("AF", "AF") == "LOCAL" and L.transfer_kind("AF", "AM") == "DISTRIBUIDA"


@pytest.mark.parametrize("amount,rate,expected", [
    ("100.00", "70.50000000", "7050.00"),     # EUR -> MZN
    ("6390.00", "0.01564945", "100.00"),      # MZN -> USD
    ("1.00", "0.01418440", "0.01"),           # MZN -> EUR, rounded half-even to the cent
    ("0.35", "0.01418440", "0.00"),
])
def test_convert_with_mzn(amount, rate, expected):
    assert L.convert(Decimal(amount), Decimal(rate)) == Decimal(expected)
