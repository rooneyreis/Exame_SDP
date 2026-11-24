"""Phase 1: automatic takeover by the copy, and return of the owner node.

For a database of the ring (America, África), with nobody running any command:
  1. a prepared (2PC phase 1) transaction is left on the owner node, then the node is stopped
  2. the copy on the next node of the ring is promoted by itself (supervisor) within seconds
  3. the prepared transaction is there (synchronous replication) and writes work through the
     same multi-host conninfo (no reconfiguration)
  4. the owner node is started: it re-syncs from the copy and takes its role back; the data
     written while it was down is on it
File name starts with "zz" so it runs after the other Phase 1 tests.
"""
import uuid

import pytest

from conftest import LOCATIONS, current_primary, local_sql, node_role, psql, run, shard_conninfo, wait_back_home, wait_until


def all_back_home() -> bool:
    return all(node_role(*LOCATIONS[c][0]) == "primary" and node_role(*LOCATIONS[c][1]) == "replica"
               for c in LOCATIONS)


@pytest.mark.parametrize("cluster", ["AM", "AF"])
def test_copy_takes_over_and_owner_takes_its_role_back(cluster):
    (home, hport), (copy, cport) = LOCATIONS[cluster]
    assert current_primary(cluster)[0] == (home, hport)
    gid = f"takeover-{uuid.uuid4()}"
    local_sql(home, "CREATE TABLE IF NOT EXISTS replication_probe (marker TEXT)", hport)
    local_sql(home, f"BEGIN; INSERT INTO replication_probe VALUES ('{gid}'); PREPARE TRANSACTION '{gid}';", hport)

    run(["docker", "stop", home])
    marker = str(uuid.uuid4())
    try:
        assert wait_until(lambda: node_role(copy, cport) == "primary", timeout=40, interval=1), \
            f"a cópia em {copy}:{cport} não assumiu o papel"
        logs = run(["docker", "logs", copy]).stdout
        assert "PROMOÇÃO" in logs and f"assume o papel de {cluster}" in logs

        # The prepared transaction reached the copy before the owner died (synchronous replication):
        # the coordinator can still decide it (here: roll it back so the test leaves no trace).
        assert local_sql(copy, f"SELECT count(*) FROM pg_prepared_xacts WHERE gid = '{gid}'", cport) == "1"
        local_sql(copy, f"ROLLBACK PREPARED '{gid}'", cport)

        # Writes keep working through the services' conninfo, now served by the copy.
        psql(shard_conninfo(cluster, "postgres"), f"INSERT INTO replication_probe VALUES ('{marker}')")
    finally:
        run(["docker", "start", home])

    assert wait_back_home(cluster, timeout=180), f"{home} não retomou o papel de {cluster}"
    # what was written while it was down is on it now
    assert local_sql(home, f"SELECT count(*) FROM replication_probe WHERE marker = '{marker}'", hport) == "1"
    assert "RETOMA" in run(["docker", "logs", copy]).stdout
    # and the other databases of the stopped node (copies it keeps) are back too
    assert wait_until(all_back_home, timeout=180, interval=3)


def test_topology_is_back_to_original():
    for cluster, (home, _) in LOCATIONS.items():
        assert current_primary(cluster)[0] == home
