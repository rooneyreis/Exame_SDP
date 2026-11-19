"""Phase 1: manual failover of a shard (America) and automatic rejoin of the old primary.

Full cycle, so the environment ends as it started:
  1. stop the primary → failover.sh promotes the replica
  2. writes work again through the same multi-host conninfo (no reconfiguration)
  3. start the old primary → it notices the peer is primary and rejoins as replica
  4. failback (same steps in the other direction)
File name starts with "zz" so it runs after the other Phase 1 tests.
"""
import uuid

import pytest

from conftest import current_primary, local_sql, node_role, psql, run, shard_conninfo, wait_until


def fail_over(region: str, gid: str) -> tuple[str, str]:
    old_primary, replica = current_primary(region)
    # A prepared (2PC phase 1) transaction left pending on the primary before it dies.
    local_sql(old_primary, f"BEGIN; INSERT INTO replication_probe VALUES ('{gid}'); PREPARE TRANSACTION '{gid}';")
    run(["docker", "stop", old_primary])
    result = run(["./scripts/failover.sh", region])
    assert f"OK: {replica} é agora o PRIMÁRIO" in result.stdout
    return old_primary, replica


def write_and_read_back(region: str) -> None:
    marker = str(uuid.uuid4())
    psql(shard_conninfo(region, "postgres"), f"INSERT INTO replication_probe VALUES ('{marker}')")
    out = psql(shard_conninfo(region, "postgres"), f"SELECT count(*) FROM replication_probe WHERE marker = '{marker}'")
    assert out.stdout.strip() == "1"


def rejoin(node: str, new_primary: str) -> None:
    run(["docker", "start", node])
    assert wait_until(lambda: node_role(node) == "replica", timeout=120, interval=2), f"{node} não voltou como réplica"
    assert wait_until(
        lambda: local_sql(new_primary, "SELECT count(*) FROM pg_stat_replication WHERE state = 'streaming'") == "1",
        timeout=60,
    )


@pytest.mark.parametrize("cycle", ["failover", "failback"])
def test_failover_cycle(cycle):
    gid = f"failover-{uuid.uuid4()}"
    old_primary, new_primary = fail_over("AM", gid)
    assert node_role(new_primary) == "primary"

    # The prepared transaction was in the WAL, so it survived on the promoted replica:
    # the coordinator can still decide it (here: roll it back, so the test leaves no trace).
    assert local_sql(new_primary, f"SELECT count(*) FROM pg_prepared_xacts WHERE gid = '{gid}'") == "1"
    local_sql(new_primary, f"ROLLBACK PREPARED '{gid}'")

    write_and_read_back("AM")

    rejoin(old_primary, new_primary)
    logs = run(["docker", "logs", old_primary]).stdout + run(["docker", "logs", old_primary]).stderr
    assert "Este nó volta como réplica" in logs

    # Data written after the failover reached the rejoined node.
    marker = str(uuid.uuid4())
    local_sql(new_primary, f"INSERT INTO replication_probe VALUES ('{marker}')")
    assert wait_until(
        lambda: local_sql(old_primary, f"SELECT count(*) FROM replication_probe WHERE marker = '{marker}'") == "1",
        timeout=15,
    )


def test_failover_refuses_while_primary_is_running():
    result = run(["./scripts/failover.sh", "EU"], check=False)
    assert result.returncode == 1
    assert "RECUSADO" in result.stderr


def test_topology_is_back_to_original():
    assert current_primary("AM") == ("pg-america", "pg-america-replica")
