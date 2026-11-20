"""Settlement orders to the partner bank's legacy system (Java), in signed XML.

Interoperability contract (identical on the Java side, legacy-bank/src):
  - XML <SettlementOrder version="1.0"> with the transfer data
  - <Sha256>     = SHA-256 (hex) of the canonical string
  - <Signature>  = Ed25519 (base64) of the canonical string, by the coordinator
  - canonical    = "SettlementOrder|1.0|TxId|FromIban|ToIban|Amount|Cur|Converted|Cur|Timestamp"
The answer <SettlementAck> is signed by the legacy bank the same way:
  - canonical    = "SettlementAck|1.0|TxId|Status|Reason|Timestamp"
Signing a canonical string (not the XML bytes) makes the signature independent of XML
formatting, which the two XML libraries (Python ElementTree, Java DOM) do differently.
"""
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal

from common.crypto import sha256_hex, sign, verify_signature


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def money(value) -> str:
    return f"{Decimal(value):.2f}"


def order_canonical(tx: dict, timestamp: str) -> str:
    return "|".join(["SettlementOrder", "1.0", str(tx["tx_id"]), tx["from_iban"], tx["to_iban"],
                     money(tx["amount"]), tx["from_currency"], money(tx["converted_amount"]),
                     tx["to_currency"], timestamp])


def build_order_xml(tx: dict, timestamp: str, private_key) -> bytes:
    canonical = order_canonical(tx, timestamp)
    root = ET.Element("SettlementOrder", version="1.0")
    ET.SubElement(root, "TxId").text = str(tx["tx_id"])
    ET.SubElement(root, "FromIban").text = tx["from_iban"]
    ET.SubElement(root, "ToIban").text = tx["to_iban"]
    ET.SubElement(root, "Amount", currency=tx["from_currency"]).text = money(tx["amount"])
    ET.SubElement(root, "ConvertedAmount", currency=tx["to_currency"]).text = money(tx["converted_amount"])
    ET.SubElement(root, "Timestamp").text = timestamp
    ET.SubElement(root, "Sha256").text = sha256_hex(canonical.encode())
    ET.SubElement(root, "Signature", alg="Ed25519").text = sign(private_key, canonical.encode())
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def parse_ack(xml_bytes: bytes) -> dict:
    # The ack comes from a trusted TLS peer and has no DTD; Python's expat also refuses
    # external entities by default.
    root = ET.fromstring(xml_bytes)
    if root.tag != "SettlementAck":
        raise ValueError(f"esperado <SettlementAck>, recebido <{root.tag}>")
    get = lambda tag: (root.findtext(tag) or "").strip()
    return {"tx_id": get("TxId"), "status": get("Status"), "reason": get("Reason"),
            "timestamp": get("Timestamp"), "sha256": get("Sha256"), "signature": get("Signature")}


def ack_canonical(ack: dict) -> str:
    return "|".join(["SettlementAck", "1.0", ack["tx_id"], ack["status"], ack["reason"], ack["timestamp"]])


def verify_ack(ack: dict, legacy_public_key) -> tuple[bool, str]:
    canonical = ack_canonical(ack).encode()
    if sha256_hex(canonical) != ack["sha256"]:
        return False, "SHA-256 do ack não corresponde"
    if not verify_signature(legacy_public_key, canonical, ack["signature"]):
        return False, "assinatura Ed25519 do banco parceiro inválida"
    if ack["status"] not in ("ACEITE", "REJEITADA"):
        return False, f"estado desconhecido: {ack['status']}"
    return True, "ok"
