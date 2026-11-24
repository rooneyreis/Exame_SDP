"""Phase 1: PostgreSQL nodes — the ring of copies, 2PC support, TLS, fragmentation, roles.

Each database lives on its owner node and keeps a copy (synchronous streaming standby) on
the next node of the ring: EU -> pg-america, AM -> pg-africa, AF -> pg-europa,
pg-core -> pg-america (common/topology.json)."""
import os
import uuid

import pytest

from conftest import LOCATIONS, core_conninfo, current_primary, local_sql, psql, shard_conninfo, wait_until

REGIONS = ["EU", "AM", "AF"]
CLUSTERS = ["CORE", *REGIONS]
ALL_LOCATIONS = [loc for c in CLUSTERS for loc in LOCATIONS[c]]


@pytest.mark.parametrize("cluster", CLUSTERS)
def test_each_database_has_a_primary_and_a_copy_on_another_node(cluster):
    (primary, pport), (copy, cport) = current_primary(cluster)
    assert primary != copy
    assert local_sql(primary, "SELECT pg_is_in_recovery()", pport) == "f"
    assert local_sql(copy, "SELECT pg_is_in_recovery()", cport) == "t"


def test_copies_form_a_ring_and_no_dedicated_replica_nodes_exist():
    assert {c: LOCATIONS[c][1][0] for c in REGIONS} == {"EU": "pg-america", "AM": "pg-africa", "AF": "pg-europa"}
    assert LOCATIONS["CORE"][1] == ("pg-america", 5434)
    nodes = {n for c in CLUSTERS for n, _ in LOCATIONS[c]}
    assert nodes == {"pg-core", "pg-europa", "pg-america", "pg-africa"}


@pytest.mark.parametrize("cluster", CLUSTERS)
def test_replication_to_the_copy_is_synchronous_and_over_tls(cluster):
    (primary, pport), _ = current_primary(cluster)
    sql = "SELECT r.state, r.sync_state, s.ssl FROM pg_stat_replication r JOIN pg_stat_ssl s USING (pid)"
    assert wait_until(lambda: local_sql(primary, sql, pport) == "streaming|sync|t", timeout=20),         local_sql(primary, sql, pport)


@pytest.mark.parametrize("cluster", CLUSTERS)
def test_insert_on_primary_appears_on_the_copy(cluster):
    (primary, pport), (copy, cport) = current_primary(cluster)
    marker = str(uuid.uuid4())
    local_sql(primary, "CREATE TABLE IF NOT EXISTS replication_probe (marker TEXT)", pport)
    local_sql(primary, f"INSERT INTO replication_probe VALUES ('{marker}')", pport)
    # synchronous: already there when the INSERT returns
    assert local_sql(copy, f"SELECT count(*) FROM replication_probe WHERE marker = '{marker}'", cport) == "1"


def test_copy_is_read_only():
    _, (copy, cport) = current_primary("EU")
    result = psql(
        f"host={copy}.global.local port={cport} dbname=bank sslmode=verify-full",
        "INSERT INTO accounts (iban, user_id, currency) VALUES ('GS-EU-99999999', gen_random_uuid(), 'EUR')",
        check=False,
    )
    assert result.returncode != 0
    assert "read-only transaction" in result.stderr


@pytest.mark.parametrize("region", REGIONS)
def test_prepare_transaction_works(region):
    """PREPARE TRANSACTION (1st phase of 2PC) and ROLLBACK PREPARED.
    That it survives a failover is tested in test_phase1_zz_failover.py."""
    (primary, port), _ = current_primary(region)
    gid = f"test-{uuid.uuid4()}"
    local_sql(primary, f"BEGIN; INSERT INTO replication_probe VALUES ('2pc'); PREPARE TRANSACTION '{gid}';", port)
    assert local_sql(primary, f"SELECT count(*) FROM pg_prepared_xacts WHERE gid = '{gid}'", port) == "1"
    local_sql(primary, f"ROLLBACK PREPARED '{gid}'", port)
    assert local_sql(primary, f"SELECT count(*) FROM pg_prepared_xacts WHERE gid = '{gid}'", port) == "0"


@pytest.mark.parametrize("node", ["pg-core", "pg-europa", "pg-america", "pg-africa"])
def test_connection_without_tls_is_rejected(node):
    result = psql(f"host={node}.global.local dbname=postgres sslmode=disable", "SELECT 1", check=False)
    assert result.returncode != 0
    assert "no encryption" in result.stderr


@pytest.mark.parametrize("node,port", ALL_LOCATIONS)
def test_connection_with_tls_verify_full_works(node, port):
    out = psql(
        f"host={node}.global.local port={port} dbname=postgres sslmode=verify-full",
        "SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()",
    ).stdout.strip()
    assert out.startswith("t|TLSv1.")


def test_certificate_hostname_is_verified():
    """verify-full checks the SAN: asking for pg-europa but reaching pg-america's IP must fail."""
    result = psql("host=pg-europa.global.local hostaddr=172.28.0.63 dbname=postgres sslmode=verify-full", "SELECT 1", check=False)
    assert result.returncode != 0
    assert "does not match host name" in result.stderr


NODE_IPS = {"pg-core": "172.28.0.60", "pg-europa": "172.28.0.61", "pg-america": "172.28.0.63", "pg-africa": "172.28.0.65"}


@pytest.mark.parametrize("region", REGIONS)
def test_multi_host_conninfo_reaches_the_primary(region):
    (primary, port), _ = current_primary(region)
    out = psql(shard_conninfo(region), "SELECT pg_is_in_recovery(), host(inet_server_addr()), inet_server_port()").stdout.strip()
    assert out == f"f|{NODE_IPS[primary]}|{port}"


def test_shard_only_accepts_its_own_region():
    result = psql(
        shard_conninfo("EU"),
        "INSERT INTO accounts (iban, user_id, currency) VALUES ('GS-AM-00000099', gen_random_uuid(), 'USD')",
        check=False,
    )
    assert result.returncode != 0
    assert "accounts_iban_check" in result.stderr


def test_balance_can_never_be_negative():
    result = psql(shard_conninfo("EU"), "UPDATE accounts SET balance = -1 WHERE iban = 'GS-EU-00000001'", check=False)
    assert "accounts_balance_check" in result.stderr


@pytest.mark.parametrize("region,currency", [("EU", "EUR"), ("AM", "USD"), ("AF", "MZN")])
def test_seed_accounts_exist(region, currency):
    seeded = ", ".join(f"'GS-{region}-0000000{i}'" for i in (1, 2, 3))
    out = psql(shard_conninfo(region), f"SELECT count(*), min(currency), max(currency) FROM accounts WHERE iban IN ({seeded})")
    assert out.stdout.strip() == f"3|{currency}|{currency}"


def test_fx_rates_seeded():
    out = psql(core_conninfo("coordinator"), "SELECT rate FROM fx_rates WHERE base='EUR' AND quote='USD'")
    assert out.stdout.strip() == "1.08000000"


def test_settings_for_2pc_and_timeouts():
    for node, port in ALL_LOCATIONS:
        assert local_sql(node, "SHOW max_prepared_transactions", port) == "100"
        assert local_sql(node, "SHOW lock_timeout", port) == "5s"


def test_service_role_cannot_read_another_service_database():
    result = psql(
        f"host=pg-core.global.local,pg-america.global.local port=5432,5434 target_session_attrs=read-write dbname=auth user=api_svc password={os.environ.get('API_DB_PASSWORD', 'api-pass')} sslmode=verify-full",
        "SELECT 1",
        check=False,
    )
    assert result.returncode != 0
    assert "permission denied" in result.stderr
