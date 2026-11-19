"""Database access shared by the services: routing by region and connection pools.

THE fragmentation rule of the system lives here (and only here):
  - an IBAN carries its region in the prefix: GS-EU-xxxxxxxx -> shard Europa, GS-AM-... -> shard América
  - a user carries its region in the JWT claim "region" (chosen at registration)
"""
import re

REGIONS = ("EU", "AM")
IBAN_RE = re.compile(r"^GS-(EU|AM)-[0-9]{8}$")

# Nodes of each shard: (initial primary, initial replica). After a failover the roles
# swap, which is why the conninfo lists both and lets libpq pick the writable one.
SHARD_NODES = {
    "EU": ("pg-europa.global.local", "pg-europa-replica.global.local"),
    "AM": ("pg-america.global.local", "pg-america-replica.global.local"),
}


def is_valid_iban(iban: str) -> bool:
    return bool(IBAN_RE.match(iban))


def region_of_iban(iban: str) -> str:
    match = IBAN_RE.match(iban)
    if not match:
        raise ValueError(f"IBAN inválido: {iban!r}")
    return match.group(1)


def shard_conninfo(region: str, user: str, password: str, ca_file: str, dbname: str = "bank") -> str:
    """libpq multi-host conninfo with automatic failover to the writable node."""
    primary, replica = SHARD_NODES[region]
    return (
        f"host={primary},{replica} port=5432,5432 dbname={dbname} user={user} password={password} "
        f"target_session_attrs=read-write sslmode=verify-full sslrootcert={ca_file} "
        f"connect_timeout=3 application_name={user}"
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

    def __init__(self, conninfos: dict[str, str]):
        self.pools = {region: make_pool(conninfo) for region, conninfo in conninfos.items()}

    async def open(self) -> None:
        for pool in self.pools.values():
            await pool.open(wait=False)

    async def close(self) -> None:
        for pool in self.pools.values():
            await pool.close()

    def for_region(self, region: str):
        return self.pools[region]

    def for_iban(self, iban: str):
        return self.pools[region_of_iban(iban)]
