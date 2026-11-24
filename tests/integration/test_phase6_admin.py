"""Phase 6: audit chain validation, shared daily report with NFS locks, cluster status."""
import asyncio
import ssl
import time
from decimal import Decimal

import httpx
import pytest

from conftest import REPO

CA = str(REPO / "infra" / "certs" / "ca.crt")
STAFF = "Staff#2026"


@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url="https://localhost", verify=ssl.create_default_context(cafile=CA), timeout=60) as c:
        yield c


def login(http, email):
    r = http.post("/auth/login", json={"email": email, "password": STAFF})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def auditor(http):
    return login(http, "auditor@globalscale.test")


@pytest.fixture(scope="module")
def operador(http):
    return login(http, "operador@globalscale.test")


@pytest.fixture(scope="module")
def admin(http):
    return login(http, "admin@globalscale.test")


def test_audit_chains_of_all_nodes_are_valid(http, auditor):
    r = http.get("/admin/audit", headers=auditor)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"], {k: v for k, v in body["files"].items() if not v["ok"]}
    assert {"auth.log", "coordinator.log"} <= set(body["files"])   # api-*.log appear after their first write of the day


def test_audit_requires_auditor(http, operador):
    assert http.get("/admin/audit", headers=operador).status_code == 403


def test_audit_of_unknown_day_is_404(http, auditor):
    assert http.get("/admin/audit", params={"date": "1999-01-01"}, headers=auditor).status_code == 404


def test_concurrent_deposits_from_both_apis_lose_no_report_update(http, operador, auditor):
    """20 deposits at the same time, spread by nginx over api-1 and api-2: two different
    containers update the SAME report file on the NFS. With fcntl.lockf the count is exact."""
    def eu_deposits():
        report = http.get("/admin/reports", headers=auditor).json()
        return report.get("cash", {}).get("DEPOSITO", {}).get("EU", {"count": 0})["count"]

    before = eu_deposits()

    async def burst():
        async with httpx.AsyncClient(base_url="https://localhost", verify=ssl.create_default_context(cafile=CA),
                                     timeout=60) as c:
            rs = await asyncio.gather(*(c.post("/accounts/GS-EU-00000002/deposit", json={"amount": "0.01"},
                                               headers=operador) for _ in range(20)))
        return rs

    responses = asyncio.run(burst())
    assert all(r.status_code == 200 for r in responses)
    assert {r.headers["X-Served-By"] for r in responses} == {"api-1", "api-2"}
    time.sleep(1)
    assert eu_deposits() == before + 20


def test_report_counts_transfers_by_state_and_region(http, auditor):
    report = http.get("/admin/reports", headers=auditor).json()
    assert report["transfers"]["by_state"].get("CONFIRMADA", 0) > 0
    assert set(report["updates_by_node"]) >= {"coordinator", "api-1", "api-2"}
    assert Decimal(report["transfers"]["volume_by_region"]["EU"]["EUR"]) > 0


def test_status_shows_every_node(http, admin):
    body = http.get("/admin/status", headers=admin).json()
    assert body["all_up"], body
    # every database in its two locations of the ring: the owner is the primary, the copy follows it
    assert body["databases"]["EU@pg-europa:5432"]["role"] == "primário"
    assert body["databases"]["EU@pg-america:5433"]["role"] == "cópia (standby)"
    assert body["databases"]["EU@pg-europa:5432"]["replicas_streaming"] == 1
    assert body["databases"]["EU@pg-europa:5432"]["synchronous"] is True
    assert body["clusters_available"] == {"CORE": True, "EU": True, "AM": True, "AF": True}
    assert all(d["ssl"] == "on" and d["prepared_xacts"] == 0 for d in body["databases"].values())
    assert {"auth", "coordinator", "legacy-bank", "api-1", "api-2"} <= set(body["services"])
    assert body["nfs"]["up"]


def test_status_requires_admin_or_auditor(http, operador):
    assert http.get("/admin/status", headers=operador).status_code == 403
