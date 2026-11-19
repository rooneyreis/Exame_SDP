"""Pure business rules of the auth service (no database, no HTTP): unit-tested."""
import re
from datetime import date, datetime, timedelta

MIN_AGE = 18
MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=15)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[0-9]{9,15}$")


def password_problems(password: str) -> list[str]:
    """Returns the list of rules the password breaks (empty list = strong password)."""
    problems = []
    if len(password) < 8:
        problems.append("pelo menos 8 caracteres")
    if not re.search(r"[A-Z]", password):
        problems.append("uma letra maiúscula")
    if not re.search(r"[0-9]", password):
        problems.append("um dígito")
    if not re.search(r"[^A-Za-z0-9]", password):
        problems.append("um símbolo")
    return problems


def age_on(birth_date: date, today: date) -> int:
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1  # birthday not reached yet this year
    return years


def is_adult(birth_date: date, today: date) -> bool:
    return age_on(birth_date, today) >= MIN_AGE


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email))


def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_RE.match(phone))


def default_currency(region: str) -> str:
    return {"EU": "EUR", "AM": "USD"}[region]


def is_locked(locked_until: datetime | None, now: datetime) -> bool:
    return locked_until is not None and locked_until > now


def after_failed_login(failed_attempts: int, now: datetime) -> tuple[int, datetime | None]:
    """New (failed_attempts, locked_until) after a wrong password.
    The 5th consecutive failure locks the account for 15 minutes and resets the counter."""
    attempts = failed_attempts + 1
    if attempts >= MAX_FAILED_ATTEMPTS:
        return 0, now + LOCK_DURATION
    return attempts, None
