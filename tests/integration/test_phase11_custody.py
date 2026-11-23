"""Phase 11: custody while a region is TOTALLY down (primary and replica).

A transfer to an África account while África is down is confirmed and the money is kept in
custody in another active shard; the owner can use it (transfer, withdraw) up to the amount
held; when África is back, the remaining amount and the history are forwarded there."""
import ssl
import time
import uuid
from decimal import Decimal

import httpx
import pytest

from conftest import REPO, node_role, psql, run, wait_until

CA = str(REPO / "infra" / "certs" / "ca.crt")
STAFF, CLIENT = "Staff#2026", "Cliente#2026"
EU1, AF1 = "GS-EU-00000001", "GS-AF-00000001"
CORE = "host=pg-core.global.local dbname=coordinator sslmode=verify-full"
EU_SHARD = ("host=pg-europa.global.local,pg-europa-replica.global.local target_session_attrs=read-write "
            "dbname=bank sslmode=verify-full")


@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url="https://localhost", verify=ssl.create_default_context(cafile=CA), timeout=90) as c:
        yield c


def login(http, email, password):
    r = http.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def transfer(http, headers, src, dst, amount):
    return http.post("/transfers", json={"from_iban": src, "to_iban": dst, "amount": amount},
                     headers={**headers, "Idempotency-Key": f"custody-{uuid.uuid4()}"})


def balance(http, operador, iban) -> Decimal:
    return Decimal(http.get(f"/accounts/{iban}", headers=operador).json()["balance"])


def start_africa():
    run(["docker", "start", "pg-africa"])
    assert wait_until(lambda: node_role("pg-africa") == "primary", timeout=90, interval=2)
    run(["docker", "start", "pg-africa-replica"])
    assert wait_until(lambda: node_role("pg-africa-replica") == "replica", timeout=120, interval=2)


def test_custody_while_africa_is_down_then_forwarded(http):
    operador = login(http, "operador@globalscale.test", STAFF)
    auditor = login(http, "auditor@globalscale.test", STAFF)
    ana = login(http, "ana.silva@cliente.test", CLIENT)        # EU
    amina = login(http, "amina.mussa@cliente.test", CLIENT)    # AF
    # The coordinator copies the accounts to the directory (pg-core) every 30 s.
    assert wait_until(lambda: psql(CORE, f"SELECT 1 FROM account_directory WHERE iban = '{AF1}'").stdout.strip() == "1",
                      timeout=60, interval=2)
    af_before = balance(http, operador, AF1)

    run(["docker", "stop", "pg-africa", "pg-africa-replica"])
    try:
        assert wait_until(lambda: http.get("/accounts", headers=amina).headers.get("X-Unavailable-Regions") == "AF",
                          timeout=60, interval=2)
        # 1. A transfer TO África is confirmed: the credit stays in custody in Europa.
        r = transfer(http, ana, EU1, AF1, "10.00")
        assert r.status_code == 201, r.text
        tx = r.json()
        assert tx["state"] == "CONFIRMADA" and tx["routing"] == "CUSTODIA"
        assert tx["credit_region"] == "EU" and tx["to_region"] == "AF"
        assert "DESVIO_CUSTODIA" in [e["event"] for e in tx["events"]]
        credited = Decimal(tx["converted_amount"])                 # in MZN
        first_tx = tx["tx_id"]

        # 2. The owner sees the amount held (usable) on the África account.
        af = next(a for a in http.get("/accounts", headers=amina).json() if a["iban"] == AF1)
        assert af["region_unavailable"] is True
        assert Decimal(af["balance"]) == credited and set(af["held_in"]) == {"EU"}

        # 3. ...and can use it: a transfer up to the amount held, debited from the custody.
        r = transfer(http, amina, AF1, EU1, "100.00")
        assert r.status_code == 201, r.text
        assert r.json()["debit_region"] == "EU" and r.json()["kind"] == "LOCAL"
        # but never more than what is held
        r = transfer(http, amina, AF1, EU1, str(credited))
        assert r.status_code == 422 and "valor retido" in r.json()["failure_reason"]

        # 4. A withdrawal at the desk also comes out of the custody.
        r = http.post(f"/accounts/{AF1}/withdraw", json={"amount": "5.00"}, headers=operador)
        assert r.status_code == 200, r.text
        assert r.json()["custody_region"] == "EU"
        assert Decimal(r.json()["balance"]) == credited - 105

        moves = http.get(f"/accounts/{AF1}/movements", headers=amina).json()
        assert len(moves) == 3 and all(m["pending_forward"] and m["via_region"] == "EU" for m in moves)
    finally:
        start_africa()

    # 5. África is back: the remaining amount and the history are forwarded there.
    expected = af_before + credited - 105
    assert wait_until(lambda: balance(http, operador, AF1) == expected, timeout=120, interval=3)
    replayed = http.get(f"/accounts/{AF1}/movements?limit=3", headers=amina).json()   # the 3 most recent
    assert all(m["via_region"] == "EU" for m in replayed)
    assert sorted(m["origin"] for m in replayed) == ["LEVANTAMENTO", "TRANSFERENCIA", "TRANSFERENCIA"]
    assert first_tx in {m["tx_id"] for m in replayed}
    af = next(a for a in http.get("/accounts", headers=amina).json() if a["iban"] == AF1)
    assert af["region_unavailable"] is False
    events = [e["event"] for e in http.get(f"/transfers/{first_tx}", headers=ana).json()["events"]]
    assert "REENCAMINHADA_PARA_AF" in events
    assert psql(EU_SHARD, f"SELECT balance FROM custody_accounts WHERE target_iban = '{AF1}'").stdout.strip() == "0.00"
    assert psql(CORE, "SELECT count(*) FROM custody_forwards WHERE state IN ('PREPARANDO','DECISAO_COMMIT')"
                ).stdout.strip() == "0"

    # 6. Nothing lost, nothing duplicated.
    time.sleep(1)
    result = http.get("/admin/consistency", headers=auditor).json()
    assert result["ok"], result["problems"]


def test_primary_down_with_replica_up_is_pending_not_custody(http):
    """Only a TOTALLY down region goes to custody. With the replica up the transfer stays
    PENDENTE (direct route, nothing moved) and is completed when the primary is back."""
    ana = login(http, "ana.silva@cliente.test", CLIENT)
    run(["docker", "stop", "pg-africa"])
    try:
        r = transfer(http, ana, EU1, AF1, "1.00")
        assert r.status_code == 202, r.text
        tx = r.json()
        assert tx["state"] == "PENDENTE" and tx["routing"] == "DIRETA" and tx["credit_region"] == "AF"
    finally:
        run(["docker", "start", "pg-africa"])
        assert wait_until(lambda: node_role("pg-africa") == "primary", timeout=90, interval=2)
    assert wait_until(lambda: http.get(f"/transfers/{tx['tx_id']}", headers=ana).json()["state"] == "CONFIRMADA",
                      timeout=90, interval=3)
