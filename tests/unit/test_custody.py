"""Custódia de créditos para uma região totalmente em baixo (common/custody.py) e a
escolha do shard de cada perna da transferência (logic.plan_legs)."""
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from common import custody
from coordinator_service import logic as L


# ---------- onde fica um crédito ----------

def test_credit_goes_to_the_first_active_shard_in_the_global_order():
    assert custody.credit_holder("AF", ["AM", "EU"], {}) == "EU"
    assert custody.credit_holder("AF", ["AM"], {}) == "AM"


def test_credit_joins_the_shard_that_already_holds_money_for_the_account():
    assert custody.credit_holder("AF", ["EU", "AM"], {"AM": D("10.00")}) == "AM"


def test_credit_never_stays_in_the_region_that_is_down():
    assert custody.credit_holder("EU", ["EU", "AM"], {}) == "AM"


def test_credit_with_every_other_shard_down_has_no_holder():
    assert custody.credit_holder("AF", [], {}) is None


# ---------- de onde sai um débito ----------

def test_debit_comes_from_a_shard_with_enough_held():
    assert custody.debit_holder({"EU": D("5.00"), "AM": D("50.00")}, D("20.00")) == "AM"
    assert custody.debit_holder({"EU": D("50.00"), "AM": D("50.00")}, D("20.00")) == "EU"


def test_debit_larger_than_any_holding_still_picks_a_shard_so_it_fails_with_insufficient_funds():
    assert custody.debit_holder({"AM": D("5.00")}, D("20.00")) == "AM"


def test_debit_without_any_holding_has_no_holder():
    assert custody.debit_holder({}, D("1.00")) is None


# ---------- reencaminhamento: saldo restante + histórico ----------

def move(i, type_, amount):
    return {"id": i, "type": type_, "amount": D(amount), "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}


def test_replay_applies_the_history_on_top_of_the_real_balance():
    history = [move(1, "CREDITO", "705.00"), move(2, "DEBITO", "100.00"), move(3, "CREDITO", "50.00")]
    replayed, final = custody.replay(D("1000.00"), history)
    assert [r.balance_after for r in replayed] == [D("1705.00"), D("1605.00"), D("1655.00")]
    assert final == D("1000.00") + custody.net_of(history) == D("1655.00")


def test_net_of_the_history_is_the_remaining_amount_forwarded():
    assert custody.net_of([move(1, "CREDITO", "705.00"), move(2, "DEBITO", "705.00")]) == 0
    assert custody.net_of([move(1, "CREDITO", "705.00"), move(2, "DEBITO", "100.00")]) == D("605.00")


def test_replay_refuses_a_history_that_spends_more_than_it_received():
    with pytest.raises(custody.CustodyError):
        custody.replay(D("0.00"), [move(1, "DEBITO", "1.00")])


# ---------- onde corre cada perna ----------

def test_direct_legs_run_in_the_regions_of_the_accounts():
    assert L.plan_legs("GS-EU-00000001", "GS-AF-00000001", "EU", "AF") == \
        [("EU", "DEBITO", "GS-EU-00000001"), ("AF", "CREDITO", "GS-AF-00000001")]


def test_credit_in_custody_in_the_origin_shard_makes_a_single_shard_transaction():
    legs = L.plan_legs("GS-EU-00000001", "GS-AF-00000001", "EU", "EU")
    assert {r for r, _, _ in legs} == {"EU"}
    assert L.transfer_kind("EU", "EU") == "LOCAL"


def test_legs_in_custody_keep_the_global_lock_order():
    # AM -> AF with África down and the credit kept in EU: EU is prepared before AM.
    assert [r for r, _, _ in L.plan_legs("GS-AM-00000001", "GS-AF-00000001", "AM", "EU")] == ["EU", "AM"]
