"""Phase 0: TLS certificates (gen-certs.sh) and application keys (gen-keys.sh)."""
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding

from conftest import REPO, run

CERTS = REPO / "infra" / "certs"
KEYS = REPO / "infra" / "keys"

SERVICES = {
    "nginx": "172.28.0.10",
    "api-1": "172.28.0.11",
    "api-2": "172.28.0.12",
    "auth": "172.28.0.20",
    "coordinator": "172.28.0.30",
    "legacy-bank": "172.28.0.40",
    "nfs": "172.28.0.50",
    "pg-core": "172.28.0.60",
    "pg-europa": "172.28.0.61",
    "pg-europa-replica": "172.28.0.62",
    "pg-america": "172.28.0.63",
    "pg-america-replica": "172.28.0.64",
}


@pytest.mark.parametrize("name", SERVICES)
def test_certificate_is_signed_by_local_ca(name):
    result = run(["openssl", "verify", "-CAfile", str(CERTS / "ca.crt"), str(CERTS / f"{name}.crt")])
    assert result.stdout.strip().endswith("OK")


@pytest.mark.parametrize("name,ip", SERVICES.items())
def test_certificate_has_dns_and_ip_sans(name, ip):
    cert = x509.load_pem_x509_certificate((CERTS / f"{name}.crt").read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert set(san.get_values_for_type(x509.DNSName)) == {name, f"{name}.global.local"}
    assert [str(a) for a in san.get_values_for_type(x509.IPAddress)] == [ip]


def test_legacy_keystore_exists():
    assert (CERTS / "legacy-bank.p12").stat().st_size > 0


@pytest.mark.parametrize("signer", ["api-1", "api-2", "coordinator", "legacy-bank"])
def test_ed25519_pair_signs_and_verifies(signer):
    private = serialization.load_pem_private_key((KEYS / "private" / f"{signer}-ed25519.pem").read_bytes(), None)
    public = serialization.load_pem_public_key((KEYS / "public" / f"{signer}-ed25519.pub.pem").read_bytes())
    assert isinstance(private, ed25519.Ed25519PrivateKey)
    message = b'{"amount":"100.00"}'
    public.verify(private.sign(message), message)  # raises InvalidSignature on failure


def test_rs256_pair_signs_and_verifies():
    private = serialization.load_pem_private_key((KEYS / "private" / "auth-rs256.pem").read_bytes(), None)
    public = serialization.load_pem_public_key((KEYS / "public" / "auth-rs256.pub.pem").read_bytes())
    assert private.key_size == 2048
    message = b"jwt-header.jwt-payload"
    signature = private.sign(message, padding.PKCS1v15(), hashes.SHA256())
    public.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())


def test_data_key_is_256_bits():
    assert len((KEYS / "private" / "auth-data.key").read_bytes()) == 32


def test_private_keys_are_owner_only():
    for key in (KEYS / "private").iterdir():
        assert key.stat().st_mode & 0o077 == 0, f"{key.name} é legível por outros utilizadores"
