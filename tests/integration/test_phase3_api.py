"""Phase 3: public API behind nginx (2 instances), accounts, deposits/withdrawals, internal accounts."""
import ssl
import uuid
from decimal import Decimal

import httpx
import pytest

from conftest import REPO, psql, shard_conninfo

CA = str(REPO / "infra" / "certs" / "ca.crt")
CLIENT_PASSWORD = "Cliente#2026"
STAFF_PASSWORD = "Staff#2026"


@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url="https://localhost", verify=ssl.create_default_context(cafile=CA), timeout=20) as c:
        yield c


def token(http, email, password):
    r = http.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def ana(http):      # EU client, owns GS-EU-00000001
    return token(http, "ana.silva@cliente.test", CLIENT_PASSWORD)


@pytest.fixture(scope="module")
def david(http):    # AM client, owns GS-AM-00000001
    return token(http, "david.smith@cliente.test", CLIENT_PASSWORD)


@pytest.fixture(scope="module")
def operador(http):
    return token(http, "operador@globalscale.test", STAFF_PASSWORD)


@pytest.fixture(scope="module")
def auditor(http):
    return token(http, "auditor@globalscale.test", STAFF_PASSWORD)


def balance(http, headers, iban) -> Decimal:
    return Decimal(http.get(f"/accounts/{iban}", headers=headers).json()["balance"])


# ---------- load balancing ----------

def test_both_instances_serve_requests(http, ana):
    served = {http.get("/accounts", headers=ana).headers["X-Served-By"] for _ in range(6)}
    assert served == {"api-1", "api-2"}


def test_requests_without_token_are_rejected(http):
    assert http.get("/accounts").status_code == 401


# ---------- region routing ----------

def test_client_sees_only_accounts_of_its_region_shard(http, ana, david):
    assert [a["iban"] for a in http.get("/accounts", headers=ana).json()] == ["GS-EU-00000001"]
    assert [a["iban"] for a in http.get("/accounts", headers=david).json()] == ["GS-AM-00000001"]


def test_me_returns_claims_and_accounts(http, ana):
    me = http.get("/me", headers=ana).json()
    assert me["role"] == "cliente" and me["region"] == "EU"
    assert me["accounts"][0]["currency"] == "EUR"


def test_client_cannot_see_another_clients_account(http, ana):
    assert http.get("/accounts/GS-AM-00000001", headers=ana).status_code == 404
    assert http.get("/accounts/GS-EU-00000002", headers=ana).status_code == 404
    assert http.get("/accounts/GS-EU-00000002/movements", headers=ana).status_code == 404


def test_operator_sees_accounts_of_both_shards(http, operador):
    assert http.get("/accounts/GS-EU-00000002", headers=operador).json()["region"] == "EU"
    assert http.get("/accounts/GS-AM-00000002", headers=operador).json()["region"] == "AM"


def test_invalid_iban_is_404(http, operador):
    assert http.get("/accounts/GS-XX-00000001", headers=operador).status_code == 404


def test_fx_rates(http, ana):
    rates = {(r["base"], r["quote"]): r["rate"] for r in http.get("/fx-rates", headers=ana).json()}
    assert rates[("EUR", "USD")] == "1.08000000"


# ---------- deposit / withdraw (local transactions) ----------

def test_deposit_and_withdraw_update_balance_and_movements(http, operador):
    iban = "GS-EU-00000003"
    before = balance(http, operador, iban)
    r = http.post(f"/accounts/{iban}/deposit", json={"amount": "100.50"}, headers=operador)
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["balance"]) == before + Decimal("100.50")
    r = http.post(f"/accounts/{iban}/withdraw", json={"amount": "0.50"}, headers=operador)
    assert Decimal(r.json()["balance"]) == before + Decimal("100.00")

    moves = http.get(f"/accounts/{iban}/movements", headers=operador).json()
    assert [m["origin"] for m in moves[:2]] == ["LEVANTAMENTO", "DEPOSITO"]
    assert [m["type"] for m in moves[:2]] == ["DEBITO", "CREDITO"]
    http.post(f"/accounts/{iban}/withdraw", json={"amount": "100.00"}, headers=operador)  # restore


def test_withdraw_more_than_balance_is_refused(http, operador):
    iban = "GS-AM-00000003"
    too_much = str(balance(http, operador, iban) + 1)
    r = http.post(f"/accounts/{iban}/withdraw", json={"amount": too_much}, headers=operador)
    assert r.status_code == 409 and "saldo insuficiente" in r.text


@pytest.mark.parametrize("amount", ["0", "-5", "1.234", "abc"])
def test_invalid_amounts_are_rejected(http, operador, amount):
    assert http.post("/accounts/GS-EU-00000003/deposit", json={"amount": amount}, headers=operador).status_code == 422


def test_client_cannot_deposit(http, ana):
    assert http.post("/accounts/GS-EU-00000001/deposit", json={"amount": "1000"}, headers=ana).status_code == 403


def test_auditor_reads_movements_but_cannot_deposit(http, auditor):
    assert http.get("/accounts/GS-EU-00000003/movements", headers=auditor).status_code == 200
    assert http.post("/accounts/GS-EU-00000003/deposit", json={"amount": "1"}, headers=auditor).status_code == 403


def test_deposit_is_in_the_right_shard_only(http, operador):
    tx = http.post("/accounts/GS-AM-00000002/deposit", json={"amount": "1.00"}, headers=operador).json()["tx_id"]
    assert psql(shard_conninfo("AM"), f"SELECT count(*) FROM movements WHERE tx_id = '{tx}'").stdout.strip() == "1"
    assert psql(shard_conninfo("EU"), f"SELECT count(*) FROM movements WHERE tx_id = '{tx}'").stdout.strip() == "0"
    http.post("/accounts/GS-AM-00000002/withdraw", json={"amount": "1.00"}, headers=operador)


# ---------- internal accounts (service token) ----------

def test_internal_accounts_requires_service_role(http, operador):
    body = {"user_id": str(uuid.uuid4()), "region": "EU", "currency": "EUR"}
    assert http.post("/internal/accounts", json=body, headers=operador).status_code == 403


def test_kyc_creates_account_once_even_if_retried(http, operador):
    n = uuid.uuid4().hex[:8]
    reg = http.post("/auth/register", json={
        "full_name": "Teste KYC", "email": f"kyc.{n}@cliente.test", "phone": f"+1202{int(n, 16) % 10**7:07d}",
        "password": "Teste#2026", "region": "AM", "document_id": f"US{n}", "birth_date": "1990-01-01"})
    user_id = reg.json()["id"]
    r = http.post(f"/admin/users/{user_id}/approve-kyc", headers=operador)
    assert r.status_code == 200, r.text
    account = r.json()["account"]
    assert account["iban"].startswith("GS-AM-") and account["currency"] == "USD" and account["created"]
    # second approval: user no longer pending
    assert http.post(f"/admin/users/{user_id}/approve-kyc", headers=operador).status_code == 409
    count = psql(shard_conninfo("AM"), f"SELECT count(*) FROM accounts WHERE user_id = '{user_id}'").stdout.strip()
    assert count == "1"


def test_health_reports_shards_and_jwks(http):
    health = http.get("/health").json()
    assert health["components"]["shard_EU"]["ok"] and health["components"]["shard_AM"]["ok"]
    assert health["components"]["jwks"]["kids"]
