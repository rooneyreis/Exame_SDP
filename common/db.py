"""Database access shared by the services: routing by region and connection pools.

THE fragmentation rule of the system lives here (and only here):
  - an IBAN carries its region in the prefix: GS-EU-xxxxxxxx -> shard Europa, GS-AM-... -> shard
    América, GS-AF-... -> shard África
  - a user carries its region in the JWT claim "region" (chosen at registration)

Single source of truth for the regions: the GSS_REGIONS setting (.env / docker-compose,
default "EU,AM,AF"). Everything else (IBAN pattern, shard nodes, base currency, the
Literal types of the request schemas) is derived from it.

Where each database lives comes from common/topology.json (also read by the supervisor of
every Postgres node): its HOME node and the node that keeps its COPY, in a ring. The copy
takes over automatically when the home fails, so every conninfo lists both locations and
lets libpq pick the one that accepts writes.
"""
import json
import os
import re
from pathlib import Path

# Every region the system knows how to run: shard node name, base currency, display name.
REGION_CATALOG = {
    "EU": {"node": "pg-europa", "currency": "EUR", "name": "Europa"},
    "AM": {"node": "pg-america", "currency": "USD", "name": "América"},
    "AF": {"node": "pg-africa", "currency": "MZN", "name": "África"},
}

REGIONS = tuple(r.strip().upper() for r in os.environ.get("GSS_REGIONS", "EU,AM,AF").split(",") if r.strip())
if unknown := [r for r in REGIONS if r not in REGION_CATALOG]:
    raise RuntimeError(f"GSS_REGIONS tem regiões desconhecidas: {unknown}")

IBAN_PATTERN = rf"^GS-({'|'.join(REGIONS)})-[0-9]{{8}}$"
IBAN_RE = re.compile(IBAN_PATTERN)

TOPOLOGY = json.loads((Path(__file__).with_name("topology.json")).read_text(encoding="utf-8"))

# {cluster: ((home host, port), (copy host, port))} for "CORE" (pg-core) and every region.
CLUSTER_LOCATIONS = {
    name: tuple((f"{host}.global.local", port) for host, port in (spec["home"], spec["copy"]))
    for name, spec in TOPOLOGY["clusters"].items() if name == "CORE" or name in REGIONS
}
SHARD_NODES = {r: CLUSTER_LOCATIONS[r] for r in REGIONS}


def locations_conninfo(cluster: str) -> str:
    """host=a,b port=p,q for a cluster (both of its locations)."""
    locs = CLUSTER_LOCATIONS[cluster]
    return f"host={','.join(h for h, _ in locs)} port={','.join(str(p) for _, p in locs)}"


def core_conninfo(dbname: str, user: str, password: str, ca_file: str) -> str:
    """pg-core (auth + coordinator databases), wherever it currently runs."""
    return (f"{locations_conninfo('CORE')} dbname={dbname} user={user} password={password} "
            f"target_session_attrs=read-write sslmode=verify-full sslrootcert={ca_file} connect_timeout=3")

# Currency of the accounts opened in each region (KYC default).
REGION_CURRENCY = {r: REGION_CATALOG[r]["currency"] for r in REGIONS}


def is_valid_iban(iban: str) -> bool:
    return bool(IBAN_RE.match(iban))


def region_of_iban(iban: str) -> str:
    match = IBAN_RE.match(iban)
    if not match:
        raise ValueError(f"IBAN inválido: {iban!r}")
    return match.group(1)


def shard_conninfo(region: str, user: str, password: str, ca_file: str, dbname: str = "bank",
                   read_only: bool = False) -> str:
    """libpq multi-host conninfo.
    read_only=False: target_session_attrs=read-write -> always the current primary (writes).
    read_only=True:  target_session_attrs=any        -> whichever location answers (the home or
                     the copy): reads keep working even in the seconds before the copy takes over."""
    attrs = "any" if read_only else "read-write"
    return (
        f"{locations_conninfo(region)} dbname={dbname} user={user} password={password} "
        f"target_session_attrs={attrs} sslmode=verify-full sslrootcert={ca_file} "
        f"connect_timeout=3 application_name={user} "
        # Detect a dead peer / network partition in seconds instead of minutes:
        # TCP keepalives + tcp_user_timeout make a blocked COMMIT PREPARED fail fast.
        f"keepalives=1 keepalives_idle=5 keepalives_interval=2 keepalives_count=2 tcp_user_timeout=8000"
    )


def make_pool(conninfo: str, max_size: int = 10):
    """Async pool tuned for failover: broken connections are discarded on checkout and
    the pool keeps trying to reconnect while a node is down."""
    from psycopg.rows import dict_row          # imported here so pure helpers above
    from psycopg_pool import AsyncConnectionPool  # can be unit-tested without psycopg

    return AsyncConnectionPool(
        conninfo, open=False, min_size=1, max_size=max_size,
        kwargs={"row_factory": dict_row},
        check=AsyncConnectionPool.check_connection,
        reconnect_timeout=24 * 3600,
        timeout=10,
    )


class ShardRouter:
    """One connection pool per region; returns the right one for a region or an IBAN."""

    def __init__(self, conninfos: dict[str, str], read_conninfos: dict[str, str] | None = None):
        self.pools = {region: make_pool(conninfo) for region, conninfo in conninfos.items()}
        self.read_pools = {region: make_pool(c, max_size=5) for region, c in (read_conninfos or {}).items()}

    async def open(self) -> None:
        for pool in [*self.pools.values(), *self.read_pools.values()]:
            await pool.open(wait=False)

    async def close(self) -> None:
        for pool in [*self.pools.values(), *self.read_pools.values()]:
            await pool.close()

    def for_region(self, region: str, read: bool = False):
        return (self.read_pools if read and self.read_pools else self.pools)[region]

    def for_iban(self, iban: str, read: bool = False):
        return self.for_region(region_of_iban(iban), read)
