from datetime import date, datetime, timedelta, timezone

import pytest

from auth_service import validation as v


@pytest.mark.parametrize("password", ["Forte#123", "Abcdefg1!", "XYZ!9abcd"])
def test_strong_passwords(password):
    assert v.password_problems(password) == []


@pytest.mark.parametrize("password,missing", [
    ("Ab1!", "pelo menos 8 caracteres"),
    ("abcdefg1!", "uma letra maiúscula"),
    ("Abcdefgh!", "um dígito"),
    ("Abcdefgh1", "um símbolo"),
])
def test_weak_passwords_report_the_missing_rule(password, missing):
    assert missing in v.password_problems(password)


def test_age_counts_birthday_not_yet_reached():
    assert v.age_on(date(2008, 11, 20), date(2026, 11, 19)) == 17
    assert v.age_on(date(2008, 11, 19), date(2026, 11, 19)) == 18


def test_is_adult():
    today = date(2026, 11, 19)
    assert v.is_adult(date(2000, 1, 1), today)
    assert not v.is_adult(date(2010, 1, 1), today)


@pytest.mark.parametrize("email,ok", [("a@b.co", True), ("ana.silva@cliente.test", True),
                                      ("sem-arroba", False), ("a@b", False), ("a b@c.com", False)])
def test_email(email, ok):
    assert v.is_valid_email(email) is ok


@pytest.mark.parametrize("phone,ok", [("+258840000001", True), ("912345678", True),
                                      ("12345", False), ("+25884abc", False)])
def test_phone(phone, ok):
    assert v.is_valid_phone(phone) is ok


def test_default_currency_by_region():
    assert v.default_currency("EU") == "EUR"
    assert v.default_currency("AM") == "USD"
    assert v.default_currency("AF") == "MZN"


NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def test_failed_logins_lock_on_the_fifth():
    attempts, locked = 0, None
    for _ in range(4):
        attempts, locked = v.after_failed_login(attempts, NOW)
        assert locked is None
    assert attempts == 4
    attempts, locked = v.after_failed_login(attempts, NOW)
    assert attempts == 0 and locked == NOW + timedelta(minutes=15)


def test_is_locked():
    assert v.is_locked(NOW + timedelta(seconds=1), NOW)
    assert not v.is_locked(NOW - timedelta(seconds=1), NOW)
    assert not v.is_locked(None, NOW)
