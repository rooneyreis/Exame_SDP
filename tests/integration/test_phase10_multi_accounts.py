"""Phase 10: several accounts per client, in different regions and currencies.

Runs in order on ONE fresh client (registered + KYC here), so the rules are tested from
a known state: request -> approval in another region, duplicates, idempotency, the 6th
account, listing with a region down, own transfers EU -> AF, the daily limit summed over
all accounts, closing, audit trail and permissions."""
import ssl
import time
import uuid
from decimal import Decimal

import httpx
import pytest

from conftest import REPO, node_role, psql, run, shard_conninfo, wait_back_home, wait_until

CA = str(REPO / "infra" / "certs" / "ca.crt")
STAFF = "Staff#2026"
STATE: dict = {}


@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url="https://localhost", verify=ssl.create_default_context(cafile=CA), timeout=90) as c:
        yield c


def login(http, email, password):
    r = http.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def staff(http):
    return {r: login(http, f"{r}@globalscale.test", STAFF) for r in ("operador", "auditor", "admin")}


@pytest.fixture(scope="module")
def client(http, staff):
    """A new EU client: registered, KYC approved (first account GS-EU in EUR)."""
    n = uuid.uuid4().hex[:8]
    email = f"multi.{n}@cliente.test"
    reg = http.post("/auth/register", json={
        "full_name": "Cliente Multi", "email": email, "phone": f"+3519{int(n, 16) % 10**8:08d}",
        "password": "Teste#2026", "region": "EU", "document_id": f"PT{n}", "birth_date": "1990-01-01"})
    assert reg.status_code == 201, reg.text
    user_id = reg.json()["id"]
    kyc = http.post(f"/admin/users/{user_id}/approve-kyc", headers=staff["operador"])
    assert kyc.status_code == 200, kyc.text
    STATE["eu"] = kyc.json()["account"]["iban"]
    return {"id": user_id, "h": login(http, email, "Teste#2026")}


def accounts(http, client):
    return {(a["region"], a["currency"]): a for a in http.get("/accounts", headers=client["h"]).json()}


def request_account(http, client, region, currency):
    return http.post("/account-requests", json={"region": region, "currency": currency}, headers=client["h"])


def transfer(http, headers, src, dst, amount):
    return http.post("/transfers", json={"from_iban": src, "to_iban": dst, "amount": amount},
                     headers={**headers, "Idempotency-Key": f"multi-{uuid.uuid4()}"})


def count_in(region, user_id, currency=None):
    extra = f" AND currency = '{currency}'" if currency else ""
    return psql(shard_conninfo(region), f"SELECT count(*) FROM accounts WHERE user_id = '{user_id}'{extra}").stdout.strip()


# ---------- seed ----------

def test_seed_client_has_accounts_in_three_regions(http):
    bruno = login(http, "bruno.costa@cliente.test", "Cliente#2026")
    got = {(a["region"], a["currency"]) for a in http.get("/accounts", headers=bruno).json()}
    assert {("EU", "EUR"), ("AM", "USD"), ("AF", "MZN")} <= got


# ---------- opening in another region ----------

def test_client_requests_account_in_africa_and_operator_approves(http, client, staff):
    r = request_account(http, client, "AF", "MZN")
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "PENDENTE" and req["kind"] == "ABERTURA"
    assert ("AF", "MZN") not in accounts(http, client)                  # nothing before the decision
    pending = http.get("/admin/account-requests?status=PENDENTE", headers=staff["operador"]).json()
    assert any(p["id"] == req["id"] for p in pending)

    ok = http.post(f"/admin/account-requests/{req['id']}/approve", headers=staff["operador"])
    assert ok.status_code == 200, ok.text
    account = ok.json()["account"]
    assert account["iban"].startswith("GS-AF-") and account["currency"] == "MZN" and account["created"]
    STATE["af"] = account["iban"]
    STATE["af_request"] = req["id"]
    # The account lives in pg-africa only, although the client registered in Europe.
    assert count_in("AF", client["id"]) == "1"
    assert count_in("EU", client["id"]) == "1" and count_in("AM", client["id"]) == "0"
    assert set(accounts(http, client)) == {("EU", "EUR"), ("AF", "MZN")}


def test_approving_twice_does_not_create_a_second_account(http, client, staff):
    again = http.post(f"/admin/account-requests/{STATE['af_request']}/approve", headers=staff["operador"])
    assert again.status_code == 409
    assert count_in("AF", client["id"], "MZN") == "1"


def test_duplicate_region_and_currency_is_refused(http, client, staff):
    assert request_account(http, client, "AF", "MZN").status_code == 409
    desk = http.post("/admin/accounts", json={"user_id": client["id"], "region": "AF", "currency": "MZN"},
                     headers=staff["operador"])
    assert desk.status_code == 409


def test_creation_is_idempotent_when_retried_after_a_failure(http, client, staff):
    """A pending request whose account was already created (e.g. the approval crashed after
    creating it): approving returns the SAME account instead of creating another."""
    req = request_account(http, client, "AM", "USD").json()
    desk = http.post("/admin/accounts", json={"user_id": client["id"], "region": "AM", "currency": "USD"},
                     headers=staff["operador"])
    assert desk.status_code == 201 and desk.json()["created"]
    ok = http.post(f"/admin/account-requests/{req['id']}/approve", headers=staff["operador"]).json()
    assert ok["account"]["iban"] == desk.json()["iban"] and ok["account"]["created"] is False
    assert count_in("AM", client["id"], "USD") == "1"
    STATE["am"] = desk.json()["iban"]


def test_reject_needs_a_reason_and_is_final(http, client, staff):
    req = request_account(http, client, "EU", "USD").json()
    assert http.post(f"/admin/account-requests/{req['id']}/reject", json={}, headers=staff["operador"]).status_code == 422
    r = http.post(f"/admin/account-requests/{req['id']}/reject", json={"reason": "documentação incompleta"},
                  headers=staff["operador"])
    assert r.status_code == 200 and r.json()["status"] == "REJEITADO"
    assert http.post(f"/admin/account-requests/{req['id']}/approve", headers=staff["operador"]).status_code == 409
    mine = http.get("/account-requests", headers=client["h"]).json()
    assert next(m for m in mine if m["id"] == req["id"])["decision_reason"] == "documentação incompleta"


def test_sixth_account_is_refused(http, client, staff):
    for region, currency in (("EU", "USD"), ("AM", "EUR")):         # 3 -> 5 active accounts
        r = http.post("/admin/accounts", json={"user_id": client["id"], "region": region, "currency": currency},
                      headers=staff["operador"])
        assert r.status_code == 201, r.text
    STATE["am_eur"] = accounts(http, client)[("AM", "EUR")]["iban"]
    assert len(accounts(http, client)) == 5
    assert http.get("/me/limits", headers=client["h"]).json()["active_accounts"] == 5
    sixth = request_account(http, client, "AF", "EUR")
    assert sixth.status_code == 409 and "máximo" in sixth.json()["detail"]
    desk = http.post("/admin/accounts", json={"user_id": client["id"], "region": "AF", "currency": "EUR"},
                     headers=staff["operador"])
    assert desk.status_code == 409


# ---------- permissions ----------

def test_only_operators_decide(http, client, staff):
    req = http.get("/admin/account-requests", headers=staff["auditor"])
    assert req.status_code == 200                                          # auditor reads
    some = req.json()[0]["id"]
    for who in (staff["auditor"], staff["admin"], client["h"]):
        assert http.post(f"/admin/account-requests/{some}/approve", headers=who).status_code == 403
    assert http.post("/admin/accounts", json={"user_id": client["id"], "region": "AF", "currency": "USD"},
                     headers=client["h"]).status_code == 403


# ---------- transfers between own accounts and the daily limit per client ----------

def test_own_transfer_eu_to_af_with_exchange_does_not_count_for_the_daily_limit(http, client, staff):
    assert http.post(f"/accounts/{STATE['eu']}/deposit", json={"amount": "1000.00"}, headers=staff["operador"]).status_code == 200
    before = http.get("/me/limits", headers=client["h"]).json()
    r = transfer(http, client["h"], STATE["eu"], STATE["af"], "100.00")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "DISTRIBUIDA" and body["state"] == "CONFIRMADA" and body["own_transfer"] is True
    assert body["converted_amount"] == "7050.00"
    acc = accounts(http, client)
    assert acc[("EU", "EUR")]["balance"] == "900.00" and acc[("AF", "MZN")]["balance"] == "7050.00"
    after = http.get("/me/limits", headers=client["h"]).json()
    assert after["sent_today_eur"] == before["sent_today_eur"]


def test_daily_limit_is_summed_over_all_accounts_of_the_client(http, client, staff):
    assert http.post(f"/accounts/{STATE['am']}/deposit", json={"amount": "500.00"}, headers=staff["operador"]).status_code == 200
    http.put("/admin/settings", json={"daily_limit_eur": "150.00"}, headers=staff["admin"]).raise_for_status()
    try:
        first = transfer(http, client["h"], STATE["eu"], "GS-EU-00000001", "100.00")      # 100 EUR
        assert first.status_code == 201, first.text
        limits = http.get("/me/limits", headers=client["h"]).json()
        assert (limits["daily_limit_eur"], limits["sent_today_eur"], limits["remaining_eur"]) == ("150.00", "100.00", "50.00")
        # 60 USD = 55.56 EUR, from ANOTHER account (América): 100 + 55.56 > 150 -> refused
        second = transfer(http, client["h"], STATE["am"], "GS-AM-00000001", "60.00")
        assert second.status_code == 422
        assert second.json()["state"] == "ABORTADA" and "limite diário do cliente" in second.json()["failure_reason"]
        assert accounts(http, client)[("AM", "USD")]["balance"] == "500.00"          # nothing debited
        # still fits: 50 EUR from the MZN account (3525 MZN = 50.00 EUR)
        third = transfer(http, client["h"], STATE["af"], "GS-AF-00000001", "3525.00")
        assert third.status_code == 201, third.text
        assert http.get("/me/limits", headers=client["h"]).json()["remaining_eur"] == "0.00"
    finally:
        http.put("/admin/settings", json={"daily_limit_eur": "50000.00"}, headers=staff["admin"])


def test_max_per_transfer_is_in_eur(http, client):
    # 10 000 EUR maximum: 800 000 MZN is ~11 348 EUR -> refused, although the account allows it
    r = transfer(http, client["h"], STATE["af"], "GS-AF-00000001", "800000.00")
    assert r.status_code == 422 and "EUR" in r.json()["detail"]


# ---------- closing ----------

def test_closing_with_balance_is_refused(http, client):
    r = http.post(f"/accounts/{STATE['eu']}/closure", headers=client["h"])
    assert r.status_code == 409 and "saldo 0" in r.json()["detail"]


def test_closing_an_empty_account(http, client, staff):
    r = http.post(f"/accounts/{STATE['am_eur']}/closure", headers=client["h"])
    assert r.status_code == 201, r.text
    assert http.post(f"/accounts/{STATE['am_eur']}/closure", headers=client["h"]).status_code == 409   # one pending
    ok = http.post(f"/admin/account-requests/{r.json()['id']}/approve", headers=staff["operador"])
    assert ok.status_code == 200, ok.text
    assert ok.json()["account"]["status"] == "ENCERRADA"
    closed = accounts(http, client)[("AM", "EUR")]
    assert closed["status"] == "ENCERRADA" and closed["closed_at"]
    # never deleted, and no longer counts as active
    assert count_in("AM", client["id"], "EUR") == "1"
    assert http.get("/me/limits", headers=client["h"]).json()["active_accounts"] == 4
    assert transfer(http, client["h"], STATE["eu"], STATE["am_eur"], "1.00").json()["state"] == "ABORTADA"


# ---------- listing with a region down ----------

def test_listing_with_a_region_down_returns_the_others(http, client):
    # África is totally down only when its node AND the node keeping its copy (pg-europa) are
    # down; meanwhile Europa keeps working, taken over by its copy on pg-america.
    run(["docker", "stop", "pg-africa", "pg-europa"])
    try:
        assert wait_until(lambda: node_role("pg-america", 5433) == "primary", timeout=60, interval=2)
        assert wait_until(lambda: http.get("/accounts", headers=client["h"]).headers.get("X-Unavailable-Regions") == "AF",
                          timeout=60, interval=2)
        r = http.get("/accounts", headers=client["h"])
        assert r.status_code == 200
        # EU and AM read from their databases; the África accounts show only the amount held in
        # custody elsewhere (phase 11), flagged as unavailable.
        assert {a["region"] for a in r.json() if not a["region_unavailable"]} == {"EU", "AM"}
        assert {a["region"] for a in r.json() if a["region_unavailable"]} <= {"AF"}
        assert http.get("/me", headers=client["h"]).json()["unavailable_regions"] == ["AF"]
    finally:
        run(["docker", "start", "pg-europa", "pg-africa"])
    assert all(wait_back_home(c, timeout=180) for c in ("EU", "AF", "AM"))
    assert wait_until(lambda: "X-Unavailable-Regions" not in http.get("/accounts", headers=client["h"]).headers,
                      timeout=60, interval=2)


# ---------- audit ----------

def test_account_lifecycle_is_in_the_audit_chain(http, staff):
    day = time.strftime("%Y-%m-%d", time.gmtime())
    events = http.get(f"/admin/audit/events?date={day}&limit=1", headers=staff["auditor"]).json()
    assert {"CONTA_PEDIDO_ABERTURA", "CONTA_ABERTURA_APROVADA", "CONTA_PEDIDO_REJEITADO",
            "CONTA_ABERTA_BALCAO", "CONTA_PEDIDO_ENCERRAMENTO", "CONTA_ENCERRADA"} <= set(events["actions"])
    # written by the api instances, in their hash chains (the demo 05 tampers another file on purpose)
    for f in ("api-1.log", "api-2.log"):
        assert events["chains"][f]["ok"], events["chains"][f]


def test_consistency_after_multi_accounts(http, staff):
    assert http.get("/admin/consistency", headers=staff["auditor"]).json()["ok"]
