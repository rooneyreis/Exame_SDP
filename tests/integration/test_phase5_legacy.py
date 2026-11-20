"""Phase 5: legacy partner bank (Java 21, XML, Ed25519) and asynchronous settlement."""
import json
import ssl
import subprocess
import uuid

import httpx
import pytest

from conftest import REPO, run, wait_until

CA = str(REPO / "infra" / "certs" / "ca.crt")


@pytest.fixture(scope="module")
def legacy_results():
    script = (REPO / "tests" / "integration" / "legacy_client.py").read_text()
    out = subprocess.run(["docker", "exec", "-i", "coordinator", "python", "-"], input=script,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# ---------- XML contract, straight to the Java server ----------

def test_valid_xml_is_accepted_with_signed_ack(legacy_results):
    assert legacy_results["valida"] == {"http": 200, "status": "ACEITE", "reason": "registada no ledger", "ack_ok": True}


def test_same_order_twice_is_idempotent(legacy_results):
    assert legacy_results["repetida"]["status"] == "ACEITE" and "idempotente" in legacy_results["repetida"]["reason"]


def test_tampered_xml_is_rejected(legacy_results):
    r = legacy_results["adulterada"]
    assert r["http"] == 400 and r["status"] == "REJEITADA" and "SHA-256" in r["reason"] and r["ack_ok"]


def test_order_signed_by_another_key_is_rejected(legacy_results):
    r = legacy_results["assinatura_falsa"]
    assert r["http"] == 400 and "assinatura" in r["reason"]


def test_order_above_limit_is_rejected(legacy_results):
    r = legacy_results["acima_do_limite"]
    assert r["http"] == 200 and r["status"] == "REJEITADA" and "limite" in r["reason"] and r["ack_ok"]


def test_malformed_xml_and_xxe_are_rejected(legacy_results):
    assert legacy_results["xml_invalido"]["http"] == 400
    assert legacy_results["xxe"]["http"] == 400 and "DOCTYPE" in legacy_results["xxe"]["reason"]


def test_listing_returns_accepted_orders(legacy_results):
    assert legacy_results["listagem_contem_valida"]


def test_ledger_has_fixed_width_records(legacy_results):
    lines = run(["docker", "exec", "legacy-bank", "cat", "/data/ledger.dat"]).stdout.splitlines()
    assert lines and all(len(l) == 121 for l in lines)
    record = next(l for l in lines if l.startswith(legacy_results["valid_tx_id"]))
    assert record[64:79] == "000000000010000" and record[79:82] == "EUR"      # 100.00 EUR in cents
    assert record[82:97] == "000000000010800" and record[97:100] == "USD"     # 108.00 USD
    assert record[120] == "A"


# ---------- end to end: transfer -> asynchronous settlement ----------

@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url="https://localhost", verify=ssl.create_default_context(cafile=CA), timeout=60) as c:
        yield c


def login(http, email, password):
    return {"Authorization": f"Bearer {http.post('/auth/login', json={'email': email, 'password': password}).json()['access_token']}"}


@pytest.fixture(scope="module")
def ana(http):
    return login(http, "ana.silva@cliente.test", "Cliente#2026")


@pytest.fixture(scope="module")
def auditor(http):
    return login(http, "auditor@globalscale.test", "Staff#2026")


def transfer(http, headers, dst, amount):
    r = http.post("/transfers", json={"from_iban": "GS-EU-00000001", "to_iban": dst, "amount": amount},
                  headers={**headers, "Idempotency-Key": f"p5-{uuid.uuid4()}"})
    assert r.status_code == 201, r.text
    return r.json()["tx_id"]


def settlement_of(http, auditor, tx_id):
    return http.get(f"/transfers/{tx_id}", headers=auditor).json()["settlement_status"]


def test_distributed_transfer_is_settled_accepted(http, ana, auditor):
    tx_id = transfer(http, ana, "GS-AM-00000002", "15.00")
    assert wait_until(lambda: settlement_of(http, auditor, tx_id) == "ACEITE", timeout=20)
    events = [e["event"] for e in http.get(f"/transfers/{tx_id}", headers=auditor).json()["events"]]
    assert events[-1] == "LIQUIDACAO_ACEITE"


def test_local_transfer_has_no_settlement(http, ana, auditor):
    tx_id = transfer(http, ana, "GS-EU-00000002", "1.00")
    assert settlement_of(http, auditor, tx_id) == "N/A"


@pytest.fixture(scope="module")
def mzn_account(http):
    """An América client whose account is in MZN (EUR -> MZN at 70.5)."""
    n = uuid.uuid4().hex[:8]
    user = http.post("/auth/register", json={
        "full_name": "Cliente Metical", "email": f"mzn.{n}@cliente.test", "phone": f"+2588{int(n, 16) % 10**8:08d}",
        "password": "Teste#2026", "region": "AM", "document_id": f"MZ{n}", "birth_date": "1990-01-01"}).json()
    operador = login(http, "operador@globalscale.test", "Staff#2026")
    r = http.post(f"/admin/users/{user['id']}/approve-kyc", json={"currency": "MZN"}, headers=operador)
    assert r.status_code == 200, r.text
    return r.json()["account"]["iban"]


def test_settlement_above_bank_limit_is_rejected(http, ana, auditor, mzn_account):
    tx_id = transfer(http, ana, mzn_account, "300.00")          # 300 EUR -> 21150.00 MZN > 20000
    assert wait_until(lambda: settlement_of(http, auditor, tx_id) == "REJEITADA", timeout=20)
    tx = http.get(f"/transfers/{tx_id}", headers=auditor).json()
    assert tx["state"] == "CONFIRMADA" and tx["converted_amount"] == "21150.00"
    assert "limite" in tx["events"][-1]["detail"]["reason"]


def test_settlement_waits_while_legacy_is_down(http, ana, auditor):
    run(["docker", "stop", "legacy-bank"])
    try:
        tx_id = transfer(http, ana, "GS-AM-00000002", "2.00")    # the transfer itself is not affected
        assert settlement_of(http, auditor, tx_id) == "PENDENTE"
    finally:
        run(["docker", "start", "legacy-bank"])
    assert wait_until(lambda: settlement_of(http, auditor, tx_id) == "ACEITE", timeout=60, interval=2)
