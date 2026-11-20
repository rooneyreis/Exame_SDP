"""Settlement XML contract on the Python side (coordinator_service/settlement.py)."""
import xml.etree.ElementTree as ET
from decimal import Decimal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from common.crypto import sha256_hex, sign, verify_signature
from coordinator_service import settlement as S

KEY = Ed25519PrivateKey.generate()
TX = {"tx_id": "0c6a332c-9e9c-5e84-9745-90c30a8af185", "from_iban": "GS-EU-00000001", "to_iban": "GS-AM-00000002",
      "amount": Decimal("12.34"), "from_currency": "EUR", "converted_amount": Decimal("13.33"), "to_currency": "USD"}
TS = "2026-11-20T10:00:00Z"


def test_canonical_string_matches_the_java_side():
    assert S.order_canonical(TX, TS) == ("SettlementOrder|1.0|0c6a332c-9e9c-5e84-9745-90c30a8af185|GS-EU-00000001|"
                                         "GS-AM-00000002|12.34|EUR|13.33|USD|2026-11-20T10:00:00Z")


def test_order_xml_has_hash_and_valid_signature():
    root = ET.fromstring(S.build_order_xml(TX, TS, KEY))
    assert root.tag == "SettlementOrder" and root.get("version") == "1.0"
    assert root.find("Amount").get("currency") == "EUR" and root.findtext("Amount") == "12.34"
    canonical = S.order_canonical(TX, TS).encode()
    assert root.findtext("Sha256") == sha256_hex(canonical)
    assert root.find("Signature").get("alg") == "Ed25519"
    assert verify_signature(KEY.public_key(), canonical, root.findtext("Signature"))


def signed_ack(status="ACEITE", reason="ok"):
    ack = {"tx_id": TX["tx_id"], "status": status, "reason": reason, "timestamp": TS}
    canonical = S.ack_canonical(ack).encode()
    xml = (f'<SettlementAck version="1.0"><TxId>{ack["tx_id"]}</TxId><Status>{status}</Status>'
           f'<Reason>{reason}</Reason><Timestamp>{TS}</Timestamp><Sha256>{sha256_hex(canonical)}</Sha256>'
           f'<Signature alg="Ed25519">{sign(KEY, canonical)}</Signature></SettlementAck>')
    return xml.encode()


def test_valid_ack_is_accepted():
    ack = S.parse_ack(signed_ack())
    assert S.verify_ack(ack, KEY.public_key()) == (True, "ok")


def test_tampered_ack_is_detected():
    xml = signed_ack("REJEITADA", "limite").replace(b"<Status>REJEITADA", b"<Status>ACEITE")
    ok, reason = S.verify_ack(S.parse_ack(xml), KEY.public_key())
    assert not ok and "SHA-256" in reason


def test_ack_signed_by_someone_else_is_detected():
    ok, reason = S.verify_ack(S.parse_ack(signed_ack()), Ed25519PrivateKey.generate().public_key())
    assert not ok and "assinatura" in reason
