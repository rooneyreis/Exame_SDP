"""Fragmentation rule: region routing by IBAN prefix (common/db.py)."""
import pytest

from common.db import is_valid_iban, region_of_iban, shard_conninfo


@pytest.mark.parametrize("iban,region", [("GS-EU-00000001", "EU"), ("GS-AM-12345678", "AM"), ("GS-AF-00000042", "AF")])
def test_region_of_iban(iban, region):
    assert region_of_iban(iban) == region


@pytest.mark.parametrize("iban", ["GS-AS-00000001", "GS-EU-1", "EU-00000001", "gs-eu-00000001",
                                  "GS-EU-00000001x", "", "GS-EU-0000000a"])
def test_invalid_ibans(iban):
    assert not is_valid_iban(iban)
    with pytest.raises(ValueError):
        region_of_iban(iban)


def test_conninfo_lists_the_owner_and_the_copy_and_requires_writable_tls():
    dsn = shard_conninfo("EU", "api_svc", "pw", "/certs/ca.crt")
    # Europa lives on pg-europa and keeps its copy on pg-america (ring)
    assert "host=pg-europa.global.local,pg-america.global.local port=5432,5433" in dsn
    assert "target_session_attrs=read-write" in dsn
    assert "sslmode=verify-full" in dsn and "sslrootcert=/certs/ca.crt" in dsn


def test_ring_of_copies():
    assert "host=pg-america.global.local,pg-africa.global.local port=5432,5433" in shard_conninfo("AM", "u", "p", "ca")
    assert "host=pg-africa.global.local,pg-europa.global.local port=5432,5433" in shard_conninfo("AF", "u", "p", "ca")


def test_read_only_conninfo_accepts_either_location():
    assert "target_session_attrs=any" in shard_conninfo("EU", "u", "p", "ca", read_only=True)
    assert "keepalives=1" in shard_conninfo("EU", "u", "p", "ca") and "tcp_user_timeout=8000" in shard_conninfo("EU", "u", "p", "ca")


def test_core_conninfo_follows_pg_core_to_its_copy():
    from common.db import core_conninfo
    dsn = core_conninfo("auth", "u", "p", "ca")
    assert "host=pg-core.global.local,pg-america.global.local port=5432,5434" in dsn
    assert "target_session_attrs=read-write" in dsn and "dbname=auth" in dsn


def test_africa_shard_nodes_and_currency():
    from common.db import REGION_CURRENCY, REGIONS, SHARD_NODES
    assert REGIONS == ("EU", "AM", "AF")
    assert SHARD_NODES["AF"] == (("pg-africa.global.local", 5432), ("pg-europa.global.local", 5433))
    assert REGION_CURRENCY == {"EU": "EUR", "AM": "USD", "AF": "MZN"}


def test_iban_pattern_is_generated_from_the_regions():
    from common.db import IBAN_PATTERN
    assert IBAN_PATTERN == r"^GS-(EU|AM|AF)-[0-9]{8}$"


def test_regions_come_from_the_environment(monkeypatch):
    """GSS_REGIONS is the single source of truth: removing a region removes its IBANs."""
    import importlib

    import common.db as db
    monkeypatch.setenv("GSS_REGIONS", "EU,AM")
    try:
        importlib.reload(db)
        assert db.REGIONS == ("EU", "AM") and not db.is_valid_iban("GS-AF-00000001")
        monkeypatch.setenv("GSS_REGIONS", "EU,XX")
        with pytest.raises(RuntimeError):
            importlib.reload(db)
    finally:
        monkeypatch.delenv("GSS_REGIONS")
        importlib.reload(db)
