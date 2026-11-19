"""Phase 0: NFS v4 shared by two containers, with an exclusive lock across nodes.

Starts nfs-test-a and nfs-test-b (see tests/integration/nfs_writer.py) at the same time.
Each increments a shared counter 200 times under fcntl.lockf: the final value must be
exactly 400, which only happens if the lock is enforced across both mounts.
"""
import pytest

from conftest import run

COMPOSE = ["docker", "compose", "--profile", "nfs-test"]


@pytest.fixture(scope="module")
def nfs_run():
    run(["docker", "compose", "up", "-d", "--wait", "nfs"])
    # Clean up THROUGH an NFS client. Deleting directly on the server (behind Ganesha's
    # back) leaves stale entries in the clients' cache while other containers keep the
    # volume mounted.
    run(COMPOSE + ["run", "--rm", "--no-deps", "nfs-test-a", "rm", "-rf", "/audit/phase0"])
    run(COMPOSE + ["rm", "-f", "-s", "nfs-test-a", "nfs-test-b"])
    run(COMPOSE + ["up", "-d", "nfs-test-a", "nfs-test-b"])
    codes = run(["docker", "wait", "gss-nfs-test-a-1", "gss-nfs-test-b-1"]).stdout.split()
    logs = run(COMPOSE + ["logs", "--no-log-prefix", "nfs-test-a", "nfs-test-b"]).stdout
    counter = run(["docker", "compose", "exec", "-T", "nfs", "cat", "/audit/phase0/counter.txt"]).stdout
    yield {"codes": codes, "logs": logs, "counter": counter.strip()}
    run(COMPOSE + ["rm", "-f", "-s", "nfs-test-a", "nfs-test-b"], check=False)


def test_both_clients_succeed(nfs_run):
    assert nfs_run["codes"] == ["0", "0"], nfs_run["logs"]


def test_each_client_reads_the_other_clients_file(nfs_run):
    assert "[node-a] VI_FICHEIRO_DO_OUTRO /audit/phase0/node-b.log" in nfs_run["logs"]
    assert "[node-b] VI_FICHEIRO_DO_OUTRO /audit/phase0/node-a.log" in nfs_run["logs"]


def test_lock_is_acquired_and_released(nfs_run):
    for node in ("node-a", "node-b"):
        assert f"[{node}] lock adquirido" in nfs_run["logs"]
        assert f"[{node}] lock libertado" in nfs_run["logs"]


def test_shared_counter_has_no_lost_updates(nfs_run):
    assert nfs_run["counter"] == "400"


def test_audit_is_an_nfs4_mount():
    mounts = run(COMPOSE + ["run", "--rm", "--no-deps", "nfs-test-a", "cat", "/proc/mounts"]).stdout
    line = next(l for l in mounts.splitlines() if " /audit " in l)
    assert " nfs4 " in line and "addr=172.28.0.50" in line
