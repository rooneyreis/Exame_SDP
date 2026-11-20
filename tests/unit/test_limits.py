"""Limits per client (common/limits.py): in EUR, summed over all the client's accounts."""
from decimal import Decimal as D

from common import limits


def test_to_eur_rounds_half_even_to_the_cent():
    assert limits.to_eur(D("100.00"), None) == D("100.00")
    assert limits.to_eur(D("60.00"), D("0.92592593")) == D("55.56")      # USD -> EUR
    assert limits.to_eur(D("3525.00"), D("0.01418440")) == D("50.00")    # MZN -> EUR


def test_daily_limit_counts_what_was_already_sent_from_any_account():
    assert limits.daily_problem(D("100.00"), D("50.00"), D("150.00")) is None
    problem = limits.daily_problem(D("100.00"), D("55.56"), D("150.00"))
    assert problem and "155.56 EUR > 150.00 EUR" in problem and "todas as contas" in problem


def test_max_per_transfer_is_compared_in_eur():
    assert limits.max_problem(D("10000.00"), D("10000.00")) is None
    assert "EUR" in limits.max_problem(D("11347.53"), D("10000.00"))


def test_defaults():
    assert limits.DEFAULTS["max_accounts_per_client"] == 5
    assert limits.DEFAULTS["daily_limit_eur"] == D("50000.00")
