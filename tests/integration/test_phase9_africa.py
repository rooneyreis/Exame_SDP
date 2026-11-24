"""Phase 9: third region, África (AF, MZN) — routing, KYC, local and 2PC transfers,
abort and recovery with the África shard as participant, consistency across 3 shards."""
import ssl
import threading
import time
import uuid
from decimal import Decimal

import httpx
import pytest

from conftest import REPO, local_sql, psql, run, shard_conninfo, wait_back_home, wait_until

CA = str(REPO / "infra" / "certs" / "ca.crt")
CLIENT_PASSWORD = "Cliente#2026"
STAFF_PASSWORD = "Staff#2026"
ALL = ("EU", "AM", "AF")


@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url="https://localhost", verify=ssl.create_default_context(cafile=CA), timeout=90) as c:
        yield c


def login(http, email, password=CLIENT_PASSWORD):
    r = http.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def users(http):
    return {
        "ana": login(http, "ana.silva@cliente.test"),          # GS-EU-00000001 (EUR)
        "amina": login(http, "amina.mussa@cliente.test"),      # GS-AF-00000001 (MZN)
        "jorge": login(http, "jorge.macuacua@cliente.test"),   # GS-AF-00000002 (MZN)
        "operador": login(http, "operador@globalscale.test", STAFF_PASSWORD),
        "auditor": login(http, "auditor@globalscale.test", STAFF_PASSWORD),
        "admin": login(http, "admin@globalscale.test", STAFF_PASSWORD),
    }


@pytest.fixture(autouse=True)
def chaos_off(http, users):
    yield
    http.post("/admin/chaos", json={"off": True}, headers=users["admin"])


def transfer(http, headers, src, dst, amount, key=None):
    return http.post("/transfers", json={"from_iban": src, "to_iban": dst, "amount": amount},
                     headers={**headers, "Idempotency-Key": key or f"af-{uuid.uuid4()}"})


def balance(http, users, iban) -> Decimal:
    return Decimal(http.get(f"/accounts/{iban}", headers=users["operador"]).json()["balance"])


def events(body):
    return [e["event"] for e in body["events"]]


def movements_of(tx_id):
    return {r: psql(shard_conninfo(r), f"SELECT count(*) FROM movements WHERE tx_id = '{tx_id}'").stdout.strip()
            for r in ALL}


def no_prepared_left():
    return all(local_sql(n, "SELECT count(*) FROM pg_prepared_xacts") == "0"
               for n in ("pg-europa", "pg-america", "pg-africa"))


# ---------- routing and accounts ----------

def test_africa_client_sees_mzn_account_from_africa_shard(http, users):
    me = http.get("/me", headers=users["amina"]).json()
    assert me["region"] == "AF"
    accounts = http.get("/accounts", headers=users["amina"]).json()
    # the seeded AF account (closed accounts opened elsewhere during demos are ignored)
    assert [(a["iban"], a["currency"]) for a in accounts if a["status"] != "ENCERRADA"] == [("GS-AF-00000001", "MZN")]
    # The row physically lives in pg-africa and nowhere else.
    assert psql(shard_conninfo("AF"), "SELECT count(*) FROM accounts WHERE iban = 'GS-AF-00000001'").stdout.strip() == "1"
    assert psql(shard_conninfo("EU"), "SELECT count(*) FROM accounts WHERE iban LIKE 'GS-AF-%'").stdout.strip() == "0"


def test_africa_shard_refuses_ibans_of_other_regions():
    result = psql(shard_conninfo("AF"),
                  "INSERT INTO accounts (iban, user_id, currency) VALUES ('GS-EU-77777777', gen_random_uuid(), 'EUR')",
                  check=False)
    assert result.returncode != 0 and "accounts_iban_check" in result.stderr


def test_register_and_kyc_open_a_gs_af_account_in_mzn(http, users):
    n = uuid.uuid4().hex[:8]
    reg = http.post("/auth/register", json={
        "full_name": "Teste África", "email": f"af.{n}@cliente.test", "phone": f"+25882{int(n, 16) % 10**7:07d}",
        "password": "Teste#2026", "region": "AF", "document_id": f"MZ{n}", "birth_date": "1992-03-01"})
    assert reg.status_code in (200, 201), reg.text
    assert reg.json()["region"] == "AF"
    r = http.post(f"/admin/users/{reg.json()['id']}/approve-kyc", headers=users["operador"])
    assert r.status_code == 200, r.text
    account = r.json()["account"]
    assert account["iban"].startswith("GS-AF-") and account["currency"] == "MZN"
    row = psql(shard_conninfo("AF"), f"SELECT count(*), max(daily_limit) FROM accounts WHERE iban = '{account['iban']}'").stdout.strip()
    assert row == "1|2500000.00"          # daily limit in MZN, same order of magnitude as 50 000 EUR


def test_unknown_region_is_refused_at_registration(http):
    r = http.post("/auth/register", json={
        "full_name": "Teste Ásia", "email": f"as.{uuid.uuid4().hex[:8]}@cliente.test", "phone": "+81312345678",
        "password": "Teste#2026", "region": "AS", "document_id": "JP1234567", "birth_date": "1990-01-01"})
    assert r.status_code == 422


# ---------- transfers ----------

def test_local_transfer_af_to_af(http, users):
    b_from, b_to = balance(http, users, "GS-AF-00000001"), balance(http, users, "GS-AF-00000002")
    r = transfer(http, users["amina"], "GS-AF-00000001", "GS-AF-00000002", "500.00")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "LOCAL" and body["state"] == "CONFIRMADA"
    assert events(body) == ["INICIADA", "CONFIRMADA"]
    assert movements_of(body["tx_id"]) == {"EU": "0", "AM": "0", "AF": "2"}
    assert balance(http, users, "GS-AF-00000001") == b_from - Decimal("500.00")
    assert balance(http, users, "GS-AF-00000002") == b_to + Decimal("500.00")


def test_2pc_eu_to_af_with_eur_to_mzn(http, users):
    b_from, b_to = balance(http, users, "GS-EU-00000001"), balance(http, users, "GS-AF-00000002")
    r = transfer(http, users["ana"], "GS-EU-00000001", "GS-AF-00000002", "100.00")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "DISTRIBUIDA" and body["fx_rate"] == "70.50000000" and body["converted_amount"] == "7050.00"
    assert events(body) == ["INICIADA", "PREPARANDO", "PREPARADO_EU", "PREPARADO_AF",
                            "DECISAO_COMMIT", "COMMIT_EU", "COMMIT_AF", "CONFIRMADA"]
    assert movements_of(body["tx_id"]) == {"EU": "1", "AM": "0", "AF": "1"}
    assert balance(http, users, "GS-EU-00000001") == b_from - Decimal("100.00")
    assert balance(http, users, "GS-AF-00000002") == b_to + Decimal("7050.00")
    assert no_prepared_left()


def test_2pc_af_to_am_prepares_am_before_af(http, users):
    """Global lock order EU -> AM -> AF: AM (credit) is prepared before AF (debit)."""
    b_from = balance(http, users, "GS-AF-00000001")
    r = transfer(http, users["amina"], "GS-AF-00000001", "GS-AM-00000002", "6390.00")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["from_currency"] == "MZN" and body["to_currency"] == "USD"
    assert body["fx_rate"] == "0.01564945" and body["converted_amount"] == "100.00"
    assert events(body) == ["INICIADA", "PREPARANDO", "PREPARADO_AM", "PREPARADO_AF",
                            "DECISAO_COMMIT", "COMMIT_AM", "COMMIT_AF", "CONFIRMADA"]
    assert movements_of(body["tx_id"]) == {"EU": "0", "AM": "1", "AF": "1"}
    assert balance(http, users, "GS-AF-00000001") == b_from - Decimal("6390.00")


def test_africa_participant_failure_rolls_back_europe(http, users):
    http.post("/admin/chaos", json={"fail_participant": "AF"}, headers=users["admin"])
    before = balance(http, users, "GS-EU-00000001")
    body = transfer(http, users["ana"], "GS-EU-00000001", "GS-AF-00000003", "15.00").json()
    assert body["state"] == "ABORTADA" and "AF" in body["failure_reason"]
    assert events(body) == ["INICIADA", "PREPARANDO", "PREPARADO_EU", "VOTO_NAO_AF", "ROLLBACK_EU", "ABORTADA"]
    assert balance(http, users, "GS-EU-00000001") == before
    assert movements_of(body["tx_id"]) == {"EU": "0", "AM": "0", "AF": "0"} and no_prepared_left()


# ---------- recovery: África shard down between PREPARE and COMMIT ----------

def test_africa_shard_down_during_2pc_is_committed_by_recovery(http, users):
    http.post("/admin/chaos", json={"pause_after_prepare": 15}, headers=users["admin"])
    b_from, b_to = balance(http, users, "GS-EU-00000001"), balance(http, users, "GS-AF-00000003")
    result = {}
    worker = threading.Thread(target=lambda: result.update(
        r=transfer(http, users["ana"], "GS-EU-00000001", "GS-AF-00000003", "10.00")))
    worker.start()
    try:
        time.sleep(5)                          # both shards prepared; coordinator is paused
        run(["docker", "stop", "pg-africa"])
        worker.join(timeout=90)
        r = result["r"]
        assert r.status_code == 202, r.text    # decision taken, AF commit pending
        body = r.json()
        assert "COMMIT_EU" in events(body) and "COMMIT_PENDENTE_AF" in events(body)
    finally:
        run(["docker", "start", "pg-africa"])
    # Meanwhile the copy of África (on pg-europa) took over and the recovery committed there;
    # pg-africa re-syncs from it and takes its role back.
    assert wait_back_home("AF", timeout=180)
    tx_id = body["tx_id"]
    assert wait_until(lambda: http.get(f"/transfers/{tx_id}", headers=users["auditor"]).json().get("state")
                      == "CONFIRMADA", timeout=90, interval=2)
    final = http.get(f"/transfers/{tx_id}", headers=users["auditor"]).json()
    assert "RECUPERACAO_COMMIT_AF" in events(final)
    assert movements_of(tx_id) == {"EU": "1", "AM": "0", "AF": "1"}
    assert balance(http, users, "GS-EU-00000001") == b_from - Decimal("10.00")
    assert balance(http, users, "GS-AF-00000003") == b_to + Decimal("705.00")
    assert wait_until(no_prepared_left, timeout=30)


# ---------- cluster view ----------

def test_status_lists_the_africa_nodes(http, users):
    dbs = http.get("/admin/status", headers=users["admin"]).json()["databases"]
    home, copy = dbs["AF@pg-africa:5432"], dbs["AF@pg-europa:5433"]
    assert home["up"] and home["role"] == "primário" and home["ssl"] == "on" and home["location"] == "dono"
    assert copy["up"] and copy["role"] == "cópia (standby)" and copy["location"] == "cópia"


def test_health_reports_the_africa_shard(http):
    assert http.get("/health").json()["components"]["shard_AF"]["ok"]


def test_consistency_across_three_shards(http, users):
    result = http.get("/admin/consistency", headers=users["auditor"]).json()
    assert result["ok"], result["problems"]
    assert result["prepared_xacts"] == {"EU": [], "AM": [], "AF": []}
