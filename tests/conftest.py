import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

SHARD_NODES = {
    "EU": ("pg-europa", "pg-europa-replica"),
    "AM": ("pg-america", "pg-america-replica"),
}


def run(cmd: list[str], check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    """Runs a command from the repository root and returns its output as text."""
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, check=check, timeout=timeout)


def psql(conninfo: str, sql: str, check: bool = True) -> subprocess.CompletedProcess:
    """Runs SQL from the pgclient container (on globalnet, over the network, with TLS)."""
    return run(
        ["docker", "compose", "run", "--rm", "-T", "pgclient", conninfo, "-tA", "-c", sql],
        check=check,
    )


def local_sql(container: str, sql: str) -> str:
    """Runs SQL inside a Postgres container through its Unix socket (admin checks)."""
    return run(["docker", "exec", container, "psql", "-U", "postgres", "-tA", "-c", sql]).stdout.strip()


def shard_conninfo(region: str, dbname: str = "bank") -> str:
    """Multi-host conninfo used by every service: libpq picks the node that accepts writes."""
    primary, replica = SHARD_NODES[region]
    return (
        f"host={primary}.global.local,{replica}.global.local port=5432,5432 "
        f"target_session_attrs=read-write dbname={dbname} sslmode=verify-full"
    )


def node_role(container: str) -> str:
    """'primary', 'replica' or 'down'."""
    result = run(["docker", "exec", container, "psql", "-U", "postgres", "-tAc", "SELECT pg_is_in_recovery()"], check=False)
    return {"f": "primary", "t": "replica"}.get(result.stdout.strip(), "down")


def current_primary(region: str) -> tuple[str, str]:
    """(primary, replica) of a region right now — roles may have been swapped by a failover."""
    a, b = SHARD_NODES[region]
    return (a, b) if node_role(a) == "primary" else (b, a)


def wait_until(predicate, timeout: float = 60, interval: float = 1.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture(scope="session")
def repo() -> Path:
    return REPO
