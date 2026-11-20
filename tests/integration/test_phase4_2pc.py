"""Phase 4: 2PC coordinator — commit, abort and recovery paths, idempotency, integrity."""
import json
import ssl
import time
import uuid
from decimal import Decimal

import httpx
import pytest

from conftest import REPO, local_sql, psql, run, shard_conninfo, wait_until

CA = str(REPO / "infra" / "certs" / "ca.crt")
CLIENT_PASSWORD = "Cliente#2026"
STAFF_PASSWORD = "Staff#2026"


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
        "carla": login(http, "carla.mendes@cliente.test"),     # GS-EU-00000003 (EUR)
        "frank": login(http, "frank.miller@cliente.test"),     # GS-AM-00000003 (USD)
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
                     headers={**headers, "Idempotency-Key": key or f"t-{uuid.uuid4()}"})


def balance(http, users, iban) -> Decimal:
    return Decimal(http.get(f"/accounts/{iban}", headers=users["operador"]).json()["balance"])


def events(body):
    return [e["event"] for e in body["events"]]


def movements_of(tx_id, regions=("EU", "AM")):
    return {r: psql(shard_conninfo(r), f"SELECT count(*) FROM movements WHERE tx_id = '{tx_id}'").stdout.strip()
            for r in regions}


def no_prepared_left():
    return all(local_sql(n, "SELECT count(*) FROM pg_prepared_xacts") == "0" for n in ("pg-europa", "pg-america", "pg-africa"))


def wait_state(http, users, tx_id, state, timeout):
    return wait_until(lambda: http.get(f"/transfers/{tx_id}", headers=users["auditor"]).json().get("state") == state,
                      timeout=timeout, interval=1)


def wait_coordinator_healthy():
    assert wait_until(lambda: run(["docker", "inspect", "-f", "{{.State.Health.Status}}", "coordinator"],
                                  check=False).stdout.strip() == "healthy", timeout=60, interval=1)


# ---------- commit paths ----------

def test_local_transfer_is_one_transaction(http, users):
    r = transfer(http, users["ana"], "GS-EU-00000001", "GS-EU-00000003", "10.00")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "LOCAL" and body["state"] == "CONFIRMADA"
    assert events(body) == ["INICIADA", "CONFIRMADA"]               # no PREPARE: no 2PC
    assert movements_of(body["tx_id"]) == {"EU": "2", "AM": "0"}


def test_distributed_transfer_full_2pc_timeline(http, users):
    b_from, b_to = balance(http, users, "GS-AM-00000003"), balance(http, users, "GS-EU-00000001")
    r = transfer(http, users["frank"], "GS-AM-00000003", "GS-EU-00000001", "100.00")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "DISTRIBUIDA"
    assert body["fx_rate"] == "0.92592593" and body["converted_amount"] == "92.59"
    assert events(body) == ["INICIADA", "PREPARANDO", "PREPARADO_EU", "PREPARADO_AM",
                            "DECISAO_COMMIT", "COMMIT_EU", "COMMIT_AM", "CONFIRMADA"]
    assert movements_of(body["tx_id"]) == {"EU": "1", "AM": "1"}
    assert balance(http, users, "GS-AM-00000003") == b_from - Decimal("100.00")
    assert balance(http, users, "GS-EU-00000001") == b_to + Decimal("92.59")
    assert no_prepared_left()


def test_request_is_signed_and_hash_is_logged(http, users):
    body = transfer(http, users["ana"], "GS-EU-00000001", "GS-EU-00000003", "1.00").json()
    row = psql("host=pg-core.global.local dbname=coordinator sslmode=verify-full",
               f"SELECT length(request_signature), length(request_sha256) FROM transactions WHERE tx_id = '{body['tx_id']}'")
    assert row.stdout.strip() == "88|64"   # Ed25519 signature (64 bytes, base64) + SHA-256 hex


# ---------- idempotency ----------

def test_same_key_three_times_executes_once(http, users):
    key = f"idem-{uuid.uuid4()}"
    before = balance(http, users, "GS-EU-00000003")
    codes, ids = [], set()
    for _ in range(3):
        r = transfer(http, users["carla"], "GS-EU-00000003", "GS-AM-00000003", "5.00", key)
        codes.append(r.status_code)
        ids.add(r.json()["tx_id"])
    assert codes == [201, 200, 200] and len(ids) == 1
    assert balance(http, users, "GS-EU-00000003") == before - Decimal("5.00")
    assert movements_of(ids.pop()) == {"EU": "1", "AM": "1"}


def test_same_key_with_different_amount_is_conflict(http, users):
    key = f"idem-{uuid.uuid4()}"
    assert transfer(http, users["carla"], "GS-EU-00000003", "GS-EU-00000001", "1.00", key).status_code == 201
    assert transfer(http, users["carla"], "GS-EU-00000003", "GS-EU-00000001", "2.00", key).status_code == 409


# ---------- abort paths ----------

def test_insufficient_funds_aborts_in_phase_1(http, users):
    before = balance(http, users, "GS-EU-00000003")
    r = transfer(http, users["carla"], "GS-EU-00000003", "GS-AM-00000003", "9999.00")
    assert r.status_code == 422
    body = r.json()
    assert body["state"] == "ABORTADA" and "saldo insuficiente" in body["failure_reason"]
    assert events(body) == ["INICIADA", "PREPARANDO", "VOTO_NAO_EU", "ABORTADA"]
    assert movements_of(body["tx_id"]) == {"EU": "0", "AM": "0"}
    assert balance(http, users, "GS-EU-00000003") == before and no_prepared_left()


def test_participant_failure_rolls_back_the_prepared_one(http, users):
    """EU prepares (votes YES), AM fails (votes NO) -> EU must be rolled back."""
    http.post("/admin/chaos", json={"fail_participant": "AM"}, headers=users["admin"])
    before = balance(http, users, "GS-EU-00000001")
    body = transfer(http, users["ana"], "GS-EU-00000001", "GS-AM-00000003", "20.00").json()
    assert body["state"] == "ABORTADA" and "AM" in body["failure_reason"]
    assert events(body) == ["INICIADA", "PREPARANDO", "PREPARADO_EU", "VOTO_NAO_AM", "ROLLBACK_EU", "ABORTADA"]
    assert balance(http, users, "GS-EU-00000001") == before
    assert movements_of(body["tx_id"]) == {"EU": "0", "AM": "0"} and no_prepared_left()


def test_daily_limit_is_enforced_inside_the_shard(http, users):
    eu = "host=pg-europa.global.local,pg-europa-replica.global.local target_session_attrs=read-write dbname=bank sslmode=verify-full"
    psql(eu, "UPDATE accounts SET daily_limit = 0.50 WHERE iban = 'GS-EU-00000003'")
    try:
        body = transfer(http, users["carla"], "GS-EU-00000003", "GS-EU-00000001", "1.00").json()
        assert body["state"] == "ABORTADA" and "limite diário" in body["failure_reason"]
    finally:
        psql(eu, "UPDATE accounts SET daily_limit = 50000 WHERE iban = 'GS-EU-00000003'")


# ---------- recovery ----------

def test_crash_after_decision_is_committed_by_recovery(http, users):
    http.post("/admin/chaos", json={"crash_after_decision": True}, headers=users["admin"])
    key = f"crash-{uuid.uuid4()}"
    before = balance(http, users, "GS-AM-00000003")
    r = transfer(http, users["frank"], "GS-AM-00000003", "GS-EU-00000003", "30.00", key)
    assert r.status_code == 503
    tx_id = r.json()["tx_id"]                   # the client still knows its tx_id
    wait_coordinator_healthy()
    assert wait_state(http, users, tx_id, "CONFIRMADA", 30)
    body = http.get(f"/transfers/{tx_id}", headers=users["auditor"]).json()
    assert {"RECUPERACAO_COMMIT_EU", "RECUPERACAO_COMMIT_AM"} <= set(events(body))
    retry = transfer(http, users["frank"], "GS-AM-00000003", "GS-EU-00000003", "30.00", key)
    assert retry.status_code == 200 and retry.json()["idempotent_replay"] is True
    assert balance(http, users, "GS-AM-00000003") == before - Decimal("30.00")
    assert no_prepared_left()


def test_crash_before_decision_is_presumed_abort(http, users):
    http.post("/admin/chaos", json={"crash_after_prepare": True}, headers=users["admin"])
    before = balance(http, users, "GS-AM-00000003")
    r = transfer(http, users["frank"], "GS-AM-00000003", "GS-EU-00000003", "40.00")
    assert r.status_code == 503
    tx_id = r.json()["tx_id"]
    wait_coordinator_healthy()
    # Both shards hold a prepared transaction, but nobody decided: after 30 s -> rollback.
    assert wait_state(http, users, tx_id, "ABORTADA", 60)
    body = http.get(f"/transfers/{tx_id}", headers=users["auditor"]).json()
    assert {"RECUPERACAO_ROLLBACK_EU", "RECUPERACAO_ROLLBACK_AM"} <= set(events(body))
    assert "presumed abort" in body["failure_reason"]
    assert balance(http, users, "GS-AM-00000003") == before
    assert movements_of(tx_id) == {"EU": "0", "AM": "0"} and no_prepared_left()


# ---------- integrity ----------

def test_tampered_requests_to_coordinator_are_rejected():
    script = (REPO / "tests" / "integration" / "tamper_client.py").read_text()
    result = __import__("subprocess").run(["docker", "exec", "-i", "api-1", "python", "-"], input=script,
                                          capture_output=True, text=True, timeout=60)
    codes = json.loads(result.stdout.strip().splitlines()[-1])
    assert codes == {"montante_alterado": 401, "sha256_recalculado": 401, "sem_assinatura": 401,
                     "assinante_desconhecido": 401, "replay_antigo": 422}
    day = time.strftime("%Y-%m-%d", time.gmtime())
    audit = run(["docker", "compose", "exec", "-T", "nfs", "cat", f"/audit/{day}/coordinator.log"]).stdout
    assert "ADULTERACAO_DETETADA" in audit and "assinatura Ed25519 inválida" in audit


# ---------- api validations ----------

def test_cannot_transfer_from_someone_elses_account(http, users):
    assert transfer(http, users["carla"], "GS-EU-00000001", "GS-EU-00000003", "1.00").status_code == 404


def test_destination_must_exist(http, users):
    assert transfer(http, users["carla"], "GS-EU-00000003", "GS-AM-99999999", "1.00").status_code == 404


@pytest.mark.parametrize("amount", ["10000.01", "0", "-1", "1.001"])
def test_amount_limits(http, users, amount):
    assert transfer(http, users["carla"], "GS-EU-00000003", "GS-EU-00000001", amount).status_code == 422


def test_idempotency_key_is_required(http, users):
    r = http.post("/transfers", json={"from_iban": "GS-EU-00000003", "to_iban": "GS-EU-00000001", "amount": "1.00"},
                  headers=users["carla"])
    assert r.status_code == 422


def test_only_owner_and_staff_see_a_transfer(http, users):
    tx_id = transfer(http, users["carla"], "GS-EU-00000003", "GS-EU-00000001", "1.00").json()["tx_id"]
    assert http.get(f"/transfers/{tx_id}", headers=users["carla"]).status_code == 200
    assert http.get(f"/transfers/{tx_id}", headers=users["auditor"]).status_code == 200
    assert http.get(f"/transfers/{tx_id}", headers=users["frank"]).status_code == 404


def test_only_admin_controls_chaos(http, users):
    assert http.post("/admin/chaos", json={"off": True}, headers=users["operador"]).status_code == 403


def test_consistency_after_everything(http, users):
    result = http.get("/admin/consistency", headers=users["auditor"]).json()
    assert result["ok"], result["problems"]
    assert result["prepared_xacts"] == {"EU": [], "AM": [], "AF": []}
