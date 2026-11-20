"""Fragmentation rule: region routing by IBAN prefix (common/db.py)."""
import pytest

from common.db import is_valid_iban, region_of_iban, shard_conninfo


@pytest.mark.parametrize("iban,region", [("GS-EU-00000001", "EU"), ("GS-AM-12345678", "AM")])
def test_region_of_iban(iban, region):
    assert region_of_iban(iban) == region


@pytest.mark.parametrize("iban", ["GS-AS-00000001", "GS-EU-1", "EU-00000001", "gs-eu-00000001",
                                  "GS-EU-00000001x", "", "GS-EU-0000000a"])
def test_invalid_ibans(iban):
    assert not is_valid_iban(iban)
    with pytest.raises(ValueError):
        region_of_iban(iban)


def test_conninfo_lists_both_nodes_and_requires_writable_tls():
    dsn = shard_conninfo("EU", "api_svc", "pw", "/certs/ca.crt")
    assert "host=pg-europa.global.local,pg-europa-replica.global.local" in dsn
    assert "target_session_attrs=read-write" in dsn
    assert "sslmode=verify-full" in dsn and "sslrootcert=/certs/ca.crt" in dsn


def test_conninfo_america():
    assert "host=pg-america.global.local,pg-america-replica.global.local" in shard_conninfo("AM", "u", "p", "ca")


def test_read_only_conninfo_accepts_the_replica():
    assert "target_session_attrs=any" in shard_conninfo("EU", "u", "p", "ca", read_only=True)
    assert "keepalives=1" in shard_conninfo("EU", "u", "p", "ca") and "tcp_user_timeout=8000" in shard_conninfo("EU", "u", "p", "ca")
