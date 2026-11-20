"""Perfis Administrador / Operador / Auditor: RBAC no backend, aprovações, limites,
gestão de utilizadores, beneficiários e audit trail."""
import ssl
import uuid
from decimal import Decimal

import httpx
import pytest

from conftest import REPO, wait_until

CA = str(REPO / "infra" / "certs" / "ca.crt")
STAFF, CLIENT = "Staff#2026", "Cliente#2026"


@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url="https://localhost", verify=ssl.create_default_context(cafile=CA), timeout=60) as c:
        yield c


def login(http, email, password):
    r = http.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, (email, r.text)
    return r.json()


def auth(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture(scope="module")
def u(http):
    return {
        "admin": auth(login(http, "admin@globalscale.test", STAFF)),
        "operador": auth(login(http, "operador@globalscale.test", STAFF)),
        "auditor": auth(login(http, "auditor@globalscale.test", STAFF)),
        "bruno": auth(login(http, "bruno.costa@cliente.test", CLIENT)),
        "carla": auth(login(http, "carla.mendes@cliente.test", CLIENT)),
    }


def me_id(http, headers):
    return http.get("/me", headers=headers).json()["user_id"]


@pytest.fixture
def threshold(http, u):
    """Baixa o limiar de aprovação durante o teste e repõe-no no fim."""
    http.put("/admin/settings", json={"approval_threshold": "50.00"}, headers=u["admin"]).raise_for_status()
    yield Decimal("50.00")
    http.put("/admin/settings", json={"approval_threshold": "5000.00"}, headers=u["admin"])


def new_request(http, u, amount, src="GS-EU-00000002", dst="GS-AM-00000003"):
    return http.post("/transfer-requests", headers=u["operador"],
                     json={"from_iban": src, "to_iban": dst, "amount": amount, "beneficiary_name": "Frank Miller"})


# ---------- matriz de acesso (chamadas diretas à API) ----------

DENIED = [  # (perfil, método, caminho)
    ("operador", "PATCH", "/admin/users/00000000-0000-4000-8000-000000000003"),
    ("operador", "PUT", "/admin/settings"),
    ("operador", "POST", "/transfer-requests/00000000-0000-0000-0000-000000000000/approve"),
    ("operador", "PATCH", "/admin/accounts/GS-EU-00000001"),
    ("operador", "GET", "/admin/audit/events"),
    ("auditor", "POST", "/transfer-requests"),
    ("auditor", "POST", "/transfer-requests/00000000-0000-0000-0000-000000000000/approve"),
    ("auditor", "POST", "/transfer-requests/00000000-0000-0000-0000-000000000000/reject"),
    ("auditor", "PATCH", "/admin/users/00000000-0000-4000-8000-000000000002"),
    ("auditor", "POST", "/admin/users/00000000-0000-4000-8000-000000000002/status"),
    ("auditor", "POST", "/admin/staff"),
    ("auditor", "PUT", "/admin/settings"),
    ("auditor", "POST", "/accounts/GS-EU-00000001/deposit"),
    ("auditor", "POST", "/admin/beneficiaries"),
    ("auditor", "POST", "/admin/chaos"),
    ("admin", "POST", "/transfer-requests"),
    ("admin", "POST", "/accounts/GS-EU-00000001/deposit"),
    ("bruno", "GET", "/admin/users"),
    ("bruno", "GET", "/admin/transfers"),
    ("bruno", "POST", "/transfer-requests"),
]


@pytest.mark.parametrize("who,method,path", DENIED)
def test_backend_refuses_unauthorised_calls(http, u, who, method, path):
    r = http.request(method, path, headers=u[who], json={})
    assert r.status_code == 403, (who, method, path, r.status_code, r.text)


def test_denied_attempts_are_in_the_security_log(http, u):
    http.put("/admin/settings", json={"max_transfer_amount": "1.00"}, headers=u["auditor"])
    events = http.get("/admin/audit/events", params={"action": "ACESSO_NEGADO"}, headers=u["auditor"]).json()
    hit = next(e for e in events["items"] if e.get("path") == "/admin/settings" and e.get("method") == "PUT")
    assert hit["actor_role"] == "auditor" and hit["result"] == "NEGADO" and hit["ip"]


# ---------- operador: transferências com e sem aprovação ----------

def test_operator_transfer_below_threshold_is_executed(http, u):
    r = new_request(http, u, "12.34")
    assert r.status_code == 201, r.text
    req = r.json()["request"]
    assert req["requires_approval"] is False and req["effective_status"] == "EXECUTADA"
    tx = http.get(f"/transfers/{req['tx_id']}", headers=u["auditor"]).json()
    assert tx["state"] == "CONFIRMADA" and tx["initiated_role"] == "operador"
    assert tx["initiated_by"] == me_id(http, u["operador"]) and tx["approved_by"] is None
    # o titular vê a transferência feita em seu nome
    assert http.get(f"/transfers/{req['tx_id']}", headers=u["bruno"]).status_code == 200


def test_operator_transfer_above_threshold_waits_and_admin_approves(http, u, threshold):
    r = new_request(http, u, "60.00")
    req = r.json()["request"]
    assert req["effective_status"] == "PENDENTE_APROVACAO" and req["tx_id"] is None
    pending = http.get("/transfer-requests", params={"status": "PENDENTE_APROVACAO"}, headers=u["admin"]).json()
    assert req["id"] in {p["id"] for p in pending}

    assert http.post(f"/transfer-requests/{req['id']}/approve", headers=u["operador"]).status_code == 403
    ok = http.post(f"/transfer-requests/{req['id']}/approve", json={"reason": "verificado"}, headers=u["admin"])
    assert ok.status_code == 200, ok.text
    done = ok.json()["request"]
    assert done["effective_status"] == "EXECUTADA" and done["decided_by"] == me_id(http, u["admin"])
    tx = http.get(f"/transfers/{done['tx_id']}", headers=u["auditor"]).json()
    assert tx["approved_by"] == me_id(http, u["admin"]) and tx["initiated_role"] == "operador"
    # aprovar duas vezes não executa duas vezes
    assert http.post(f"/transfer-requests/{req['id']}/approve", headers=u["admin"]).status_code == 409


def test_admin_rejects_with_reason_and_nothing_moves(http, u, threshold):
    before = Decimal(http.get("/accounts/GS-EU-00000002", headers=u["operador"]).json()["balance"])
    req = new_request(http, u, "70.00").json()["request"]
    assert http.post(f"/transfer-requests/{req['id']}/reject", json={}, headers=u["admin"]).status_code == 422
    r = http.post(f"/transfer-requests/{req['id']}/reject", json={"reason": "beneficiário não confirmado"}, headers=u["admin"])
    assert r.status_code == 200 and r.json()["effective_status"] == "REJEITADA" and r.json()["tx_id"] is None
    assert Decimal(http.get("/accounts/GS-EU-00000002", headers=u["operador"]).json()["balance"]) == before
    assert http.post(f"/transfer-requests/{req['id']}/approve", headers=u["admin"]).status_code == 409


def test_operator_request_validations(http, u):
    assert new_request(http, u, "1.00", dst="GS-EU-00000002").status_code == 422           # mesma conta
    assert new_request(http, u, "1.00", dst="GS-AM-99999999").status_code == 404           # destino inexistente
    assert new_request(http, u, "999999.00").status_code == 422                             # acima do máximo


# ---------- administrador: limites e contas ----------

def test_configurable_max_is_enforced(http, u):
    http.put("/admin/settings", json={"max_transfer_amount": "100.00", "approval_threshold": "50.00"},
             headers=u["admin"]).raise_for_status()
    try:
        r = http.post("/transfers", json={"from_iban": "GS-EU-00000003", "to_iban": "GS-EU-00000001", "amount": "150.00"},
                      headers={**u["carla"], "Idempotency-Key": str(uuid.uuid4())})
        assert r.status_code == 422 and "máximo" in r.text
        assert http.put("/admin/settings", json={"approval_threshold": "500.00"}, headers=u["admin"]).status_code == 422
    finally:
        http.put("/admin/settings", json={"max_transfer_amount": "10000.00", "approval_threshold": "5000.00"}, headers=u["admin"])
    limits = {s["key"]: s["value"] for s in http.get("/admin/settings", headers=u["auditor"]).json()}
    assert limits == {"max_transfer_amount": "10000.00", "approval_threshold": "5000.00"}


def test_admin_blocks_an_account_and_sets_daily_limit(http, u):
    iban = "GS-EU-00000003"
    try:
        assert http.patch(f"/admin/accounts/{iban}", json={"status": "BLOQUEADA"}, headers=u["admin"]).json()["status"] == "BLOQUEADA"
        r = http.post("/transfers", json={"from_iban": iban, "to_iban": "GS-EU-00000001", "amount": "1.00"},
                      headers={**u["carla"], "Idempotency-Key": str(uuid.uuid4())})
        assert r.json()["state"] == "ABORTADA" and "BLOQUEADA" in r.json()["failure_reason"]
        http.patch(f"/admin/accounts/{iban}", json={"status": "ATIVA", "daily_limit": "0.50"}, headers=u["admin"])
        r = http.post("/transfers", json={"from_iban": iban, "to_iban": "GS-EU-00000001", "amount": "1.00"},
                      headers={**u["carla"], "Idempotency-Key": str(uuid.uuid4())})
        assert "limite diário" in r.json()["failure_reason"]
    finally:
        http.patch(f"/admin/accounts/{iban}", json={"status": "ATIVA", "daily_limit": "50000.00"}, headers=u["admin"])


# ---------- administrador: gestão de utilizadores ----------

@pytest.fixture
def staff_user(http, u):
    n = uuid.uuid4().hex[:8]
    body = {"full_name": "Teste Equipa", "email": f"eq.{n}@globalscale.test", "phone": f"+2588{int(n, 16) % 10**8:08d}",
            "password": "Teste#2026", "role": "operador"}
    r = http.post("/admin/staff", json=body, headers=u["admin"])
    assert r.status_code == 201
    return {**body, "id": r.json()["id"]}


def test_admin_edits_changes_role_blocks_and_deactivates(http, u, staff_user):
    uid = staff_user["id"]
    session = login(http, staff_user["email"], staff_user["password"])
    r = http.patch(f"/admin/users/{uid}", json={"full_name": "Teste Equipa Editado", "role": "auditor"}, headers=u["admin"])
    assert r.status_code == 200 and r.json()["role"] == "auditor"
    # mudar de perfil termina as sessões antigas
    assert http.post("/auth/refresh", json={"refresh_token": session["refresh_token"]}).status_code == 401
    assert login(http, staff_user["email"], staff_user["password"])

    assert http.post(f"/admin/users/{uid}/status", json={"action": "block", "reason": "teste"}, headers=u["admin"]).json()["status"] == "BLOQUEADA"
    assert http.post("/auth/login", json={"email": staff_user["email"], "password": staff_user["password"]}).status_code == 403
    assert http.post(f"/admin/users/{uid}/status", json={"action": "unblock"}, headers=u["admin"]).json()["status"] == "ATIVA"
    assert http.post(f"/admin/users/{uid}/status", json={"action": "deactivate"}, headers=u["admin"]).json()["status"] == "DESATIVADA"
    assert http.post("/auth/login", json={"email": staff_user["email"], "password": staff_user["password"]}).status_code == 403
    assert http.post(f"/admin/users/{uid}/status", json={"action": "block"}, headers=u["admin"]).status_code == 409
    assert http.post(f"/admin/users/{uid}/status", json={"action": "reactivate"}, headers=u["admin"]).json()["status"] == "ATIVA"


def test_nobody_changes_their_own_role_or_status(http, u):
    admin_id = me_id(http, u["admin"])
    assert http.patch(f"/admin/users/{admin_id}", json={"role": "auditor"}, headers=u["admin"]).status_code == 403
    assert http.post(f"/admin/users/{admin_id}/status", json={"action": "block"}, headers=u["admin"]).status_code == 403
    # um operador também não se promove (nem sequer tem a permissão)
    op_id = me_id(http, u["operador"])
    assert http.patch(f"/admin/users/{op_id}", json={"role": "admin"}, headers=u["operador"]).status_code == 403


def test_client_role_cannot_be_changed_to_staff(http, u):
    bruno = me_id(http, u["bruno"])
    assert http.patch(f"/admin/users/{bruno}", json={"role": "admin"}, headers=u["admin"]).status_code == 409


def test_role_change_is_audited_with_before_after_and_ip(http, u, staff_user):
    http.patch(f"/admin/users/{staff_user['id']}", json={"role": "auditor"}, headers=u["admin"])
    events = http.get("/admin/audit/events", params={"action": "PERFIL_ALTERADO"}, headers=u["auditor"]).json()
    e = next(e for e in events["items"] if e.get("target") == staff_user["id"])
    assert e["before"] == {"role": "operador"} and e["after"] == {"role": "auditor"}
    assert e["actor_role"] == "admin" and e["ip"] and e["result"] == "OK"
    assert all(c["ok"] for c in events["chains"].values())       # registos íntegros


# ---------- beneficiários no servidor ----------

def test_client_manages_own_beneficiaries_and_others_cannot_touch_them(http, u):
    r = http.post("/beneficiaries", json={"name": "Frank Miller", "iban": "GS-AM-00000003"}, headers=u["bruno"])
    assert r.status_code in (201, 409)
    mine = http.get("/beneficiaries", headers=u["bruno"]).json()
    ben = next(b for b in mine if b["iban"] == "GS-AM-00000003")
    assert ben["id"] not in {b["id"] for b in http.get("/beneficiaries", headers=u["carla"]).json()}
    assert http.patch(f"/beneficiaries/{ben['id']}", json={"favorite": True}, headers=u["carla"]).status_code == 404
    assert http.delete(f"/beneficiaries/{ben['id']}", headers=u["carla"]).status_code == 404
    assert http.patch(f"/beneficiaries/{ben['id']}", json={"favorite": True}, headers=u["bruno"]).json()["favorite"] is True
    assert http.post("/beneficiaries", json={"name": "X", "iban": "invalido"}, headers=u["bruno"]).status_code == 422


def test_operator_registers_beneficiary_for_a_client_and_auditor_only_reads(http, u):
    carla = me_id(http, u["carla"])
    iban = f"GS-AM-0000000{uuid.uuid4().int % 3 + 1}"
    r = http.post("/admin/beneficiaries", json={"owner_id": carla, "name": "Beneficiário Balcão", "iban": iban}, headers=u["operador"])
    assert r.status_code in (201, 409)
    listed = http.get("/admin/beneficiaries", params={"owner_id": carla}, headers=u["auditor"]).json()
    assert any(b["iban"] == iban for b in listed)
    created = next(b for b in listed if b["iban"] == iban)
    assert http.delete(f"/admin/beneficiaries/{created['id']}", headers=u["auditor"]).status_code == 403
    assert http.delete(f"/admin/beneficiaries/{created['id']}", headers=u["operador"]).status_code == 204


# ---------- auditor: fiscalização ----------

def test_auditor_sees_all_transfers_with_initiator_and_approver(http, u):
    data = http.get("/admin/transfers", params={"initiated_role": "operador", "limit": 50}, headers=u["auditor"]).json()
    assert data["total"] >= 1
    assert all(t["initiated_role"] == "operador" and t["initiated_by"] for t in data["items"])


def test_overview_and_suspicious_use_real_records(http, u):
    o = http.get("/admin/overview", headers=u["auditor"]).json()
    assert {"transactions", "daily", "balances", "pending_approvals", "limits"} <= o.keys()
    assert o["balances"]["EU"] and o["balances"]["AM"]
    s = http.get("/admin/suspicious", headers=u["auditor"]).json()
    assert "rules" in s and isinstance(s["findings"], list) and isinstance(s["failures"], list)


def test_consistency_still_holds_after_all_profile_operations(http, u):
    assert wait_until(lambda: http.get("/admin/consistency", headers=u["auditor"]).json()["ok"], timeout=20)
