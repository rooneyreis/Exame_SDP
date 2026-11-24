import json
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

TOPOLOGY = json.loads((REPO / "common" / "topology.json").read_text(encoding="utf-8"))
# {cluster: ((owner node, port), (node that keeps the copy, port))}, e.g. "EU": (("pg-europa", 5432), ("pg-america", 5433))
LOCATIONS = {name: (tuple(spec["home"]), tuple(spec["copy"])) for name, spec in TOPOLOGY["clusters"].items()}
SHARD_NODES = {r: (LOCATIONS[r][0][0], LOCATIONS[r][1][0]) for r in ("EU", "AM", "AF")}


def run(cmd: list[str], check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    """Runs a command from the repository root and returns its output as text."""
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, check=check, timeout=timeout)


def psql(conninfo: str, sql: str, check: bool = True) -> subprocess.CompletedProcess:
    """Runs SQL from the pgclient container (on globalnet, over the network, with TLS)."""
    return run(
        ["docker", "compose", "run", "--rm", "-T", "pgclient", conninfo, "-tA", "-c", sql],
        check=check,
    )


def local_sql(container: str, sql: str, port: int = 5432) -> str:
    """Runs SQL inside a Postgres container through its Unix socket (admin checks)."""
    return run(["docker", "exec", container, "psql", "-U", "postgres", "-p", str(port), "-tA", "-c", sql]).stdout.strip()


def locations_conninfo(cluster: str) -> str:
    (h1, p1), (h2, p2) = LOCATIONS[cluster]
    return f"host={h1}.global.local,{h2}.global.local port={p1},{p2}"


def shard_conninfo(region: str, dbname: str = "bank") -> str:
    """Multi-host conninfo used by every service: libpq picks the location that accepts writes."""
    return f"{locations_conninfo(region)} target_session_attrs=read-write dbname={dbname} sslmode=verify-full"


def core_conninfo(dbname: str) -> str:
    return f"{locations_conninfo('CORE')} target_session_attrs=read-write dbname={dbname} sslmode=verify-full"


def node_role(container: str, port: int = 5432) -> str:
    """'primary', 'replica' (the copy, a standby) or 'down', of the database on that port."""
    result = run(["docker", "exec", container, "psql", "-U", "postgres", "-p", str(port), "-tAc",
                  "SELECT pg_is_in_recovery()"], check=False)
    return {"f": "primary", "t": "replica"}.get(result.stdout.strip(), "down")


def current_primary(cluster: str) -> tuple[tuple[str, int], tuple[str, int]]:
    """((node, port) of the primary, (node, port) of the other location) right now."""
    a, b = LOCATIONS[cluster]
    return (a, b) if node_role(*a) == "primary" else (b, a)


def wait_back_home(cluster: str, timeout: float = 120) -> bool:
    """After a node comes back: its database is the primary again and the copy follows it."""
    (home, copy) = LOCATIONS[cluster]
    return wait_until(lambda: node_role(*home) == "primary" and node_role(*copy) == "replica",
                      timeout=timeout, interval=2)


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
