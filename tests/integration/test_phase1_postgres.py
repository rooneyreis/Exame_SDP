"""Phase 1: PostgreSQL nodes — replication, 2PC support, TLS, fragmentation, roles."""
import uuid

import pytest

from conftest import current_primary, local_sql, psql, shard_conninfo, wait_until

REGIONS = ["EU", "AM"]


@pytest.mark.parametrize("region", REGIONS)
def test_each_region_has_one_primary_and_one_replica(region):
    primary, replica = current_primary(region)
    assert local_sql(primary, "SELECT pg_is_in_recovery()") == "f"
    assert local_sql(replica, "SELECT pg_is_in_recovery()") == "t"


@pytest.mark.parametrize("region", REGIONS)
def test_replication_is_streaming_over_tls(region):
    primary, replica = current_primary(region)
    row = local_sql(
        primary,
        "SELECT r.application_name, r.state, s.ssl FROM pg_stat_replication r JOIN pg_stat_ssl s USING (pid)",
    )
    assert row == f"{replica}|streaming|t"


@pytest.mark.parametrize("region", REGIONS)
def test_insert_on_primary_appears_on_replica(region):
    primary, replica = current_primary(region)
    marker = str(uuid.uuid4())
    local_sql(primary, "CREATE TABLE IF NOT EXISTS replication_probe (marker TEXT)")
    local_sql(primary, f"INSERT INTO replication_probe VALUES ('{marker}')")
    assert wait_until(
        lambda: local_sql(replica, f"SELECT count(*) FROM replication_probe WHERE marker = '{marker}'") == "1",
        timeout=10,
    )


def test_replica_is_read_only():
    _, replica = current_primary("EU")
    result = psql(
        f"host={replica}.global.local dbname=bank sslmode=verify-full",
        "INSERT INTO accounts (iban, user_id, currency) VALUES ('GS-EU-99999999', gen_random_uuid(), 'EUR')",
        check=False,
    )
    assert result.returncode != 0
    assert "read-only transaction" in result.stderr


@pytest.mark.parametrize("region", REGIONS)
def test_prepare_transaction_works(region):
    """PREPARE TRANSACTION (1st phase of 2PC) and ROLLBACK PREPARED.
    That it survives a failover is tested in test_phase1_zz_failover.py."""
    primary, _ = current_primary(region)
    gid = f"test-{uuid.uuid4()}"
    local_sql(primary, f"BEGIN; INSERT INTO replication_probe VALUES ('2pc'); PREPARE TRANSACTION '{gid}';")
    assert local_sql(primary, f"SELECT count(*) FROM pg_prepared_xacts WHERE gid = '{gid}'") == "1"
    local_sql(primary, f"ROLLBACK PREPARED '{gid}'")
    assert local_sql(primary, f"SELECT count(*) FROM pg_prepared_xacts WHERE gid = '{gid}'") == "0"


@pytest.mark.parametrize("node", ["pg-core", "pg-europa", "pg-america"])
def test_connection_without_tls_is_rejected(node):
    result = psql(f"host={node}.global.local dbname=postgres sslmode=disable", "SELECT 1", check=False)
    assert result.returncode != 0
    assert "no encryption" in result.stderr


@pytest.mark.parametrize("node", ["pg-core", "pg-europa", "pg-europa-replica", "pg-america", "pg-america-replica"])
def test_connection_with_tls_verify_full_works(node):
    out = psql(
        f"host={node}.global.local dbname=postgres sslmode=verify-full",
        "SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()",
    ).stdout.strip()
    assert out.startswith("t|TLSv1.")


def test_certificate_hostname_is_verified():
    """verify-full checks the SAN: asking for pg-europa but reaching pg-america's IP must fail."""
    result = psql("host=pg-europa.global.local hostaddr=172.28.0.63 dbname=postgres sslmode=verify-full", "SELECT 1", check=False)
    assert result.returncode != 0
    assert "does not match host name" in result.stderr


NODE_IPS = {
    "pg-europa": "172.28.0.61", "pg-europa-replica": "172.28.0.62",
    "pg-america": "172.28.0.63", "pg-america-replica": "172.28.0.64",
}


@pytest.mark.parametrize("region", REGIONS)
def test_multi_host_conninfo_reaches_the_primary(region):
    primary, _ = current_primary(region)
    out = psql(shard_conninfo(region), "SELECT pg_is_in_recovery(), host(inet_server_addr())").stdout.strip()
    assert out == f"f|{NODE_IPS[primary]}"


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


@pytest.mark.parametrize("region,currency", [("EU", "EUR"), ("AM", "USD")])
def test_seed_accounts_exist(region, currency):
    out = psql(shard_conninfo(region), "SELECT count(*), min(currency), max(currency) FROM accounts WHERE iban LIKE 'GS-%-0000000_'")
    assert out.stdout.strip() == f"3|{currency}|{currency}"


def test_fx_rates_seeded():
    out = psql("host=pg-core.global.local dbname=coordinator sslmode=verify-full", "SELECT rate FROM fx_rates WHERE base='EUR' AND quote='USD'")
    assert out.stdout.strip() == "1.08000000"


def test_settings_for_2pc_and_timeouts():
    for node in ["pg-europa", "pg-europa-replica", "pg-america", "pg-america-replica"]:
        assert local_sql(node, "SHOW max_prepared_transactions") == "100"
        assert local_sql(node, "SHOW lock_timeout") == "5s"


def test_service_role_cannot_read_another_service_database():
    result = psql(
        "host=pg-core.global.local dbname=auth user=api_svc password=api-pass sslmode=verify-full",
        "SELECT 1",
        check=False,
    )
    assert result.returncode != 0
    assert "permission denied" in result.stderr
