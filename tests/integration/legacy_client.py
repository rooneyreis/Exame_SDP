"""Talks XML directly to the legacy bank. Runs INSIDE the coordinator container
(it has the coordinator signing key and the bank's public key):

    docker exec -i coordinator python - < tests/integration/legacy_client.py

Prints a JSON object {case: {"http": code, "status": ..., "reason": ..., "ack_ok": bool}}.
"""
import json
import ssl
import uuid
from decimal import Decimal

import httpx

from common.crypto import load_ed25519_private, load_ed25519_public
from coordinator_service import settlement as S

KEY = load_ed25519_private("/keys/private/coordinator-ed25519.pem")
BANK = load_ed25519_public("/keys/public/legacy-bank-ed25519.pub.pem")
client = httpx.Client(base_url="https://legacy-bank.global.local:9443", timeout=10,
                      verify=ssl.create_default_context(cafile="/certs/ca.crt"))


def order(amount="100.00", converted="108.00"):
    return {"tx_id": str(uuid.uuid4()), "from_iban": "GS-EU-00000001", "to_iban": "GS-AM-00000001",
            "amount": Decimal(amount), "from_currency": "EUR",
            "converted_amount": Decimal(converted), "to_currency": "USD"}


def send(xml: bytes):
    r = client.post("/settlement", content=xml, headers={"Content-Type": "application/xml"})
    try:
        ack = S.parse_ack(r.content)
        ok, _ = S.verify_ack(ack, BANK)
        return {"http": r.status_code, "status": ack["status"], "reason": ack["reason"], "ack_ok": ok}
    except Exception as exc:
        return {"http": r.status_code, "error": repr(exc)}


results = {}
ts = S.utc_timestamp()

valid = order()
valid_xml = S.build_order_xml(valid, ts, KEY)
results["valida"] = send(valid_xml)
results["repetida"] = send(valid_xml)                       # same order again: idempotent

# Amount changed in the XML after signing
results["adulterada"] = send(valid_xml.replace(b"<Amount currency=\"EUR\">100.00", b"<Amount currency=\"EUR\">900.00"))

# Signed by someone else (new random key): SHA-256 matches, signature does not
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
results["assinatura_falsa"] = send(S.build_order_xml(order(), ts, Ed25519PrivateKey.generate()))

# Correctly signed, but above the bank's limit (MAX_SETTLEMENT=20000)
results["acima_do_limite"] = send(S.build_order_xml(order("300.00", "21150.00"), ts, KEY))

# Not XML / XXE attempt (DOCTYPE with an external entity reading /etc/passwd)
results["xml_invalido"] = send(b"<SettlementOrder version='1.0'><TxId>")
results["xxe"] = send(b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>
<SettlementOrder version="1.0"><TxId>&e;</TxId></SettlementOrder>""")

listing = client.get("/settlements").text
results["listagem_contem_valida"] = valid["tx_id"] in listing
results["valid_tx_id"] = valid["tx_id"]
print(json.dumps(results, ensure_ascii=False))
