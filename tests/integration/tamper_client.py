"""Attacks on the api -> coordinator channel. Runs INSIDE the api-1 container
(the coordinator is not reachable from the host):

    docker exec -i api-1 python - < tests/integration/tamper_client.py

It never sends a valid request (no money moves). Prints a JSON object
{attack: HTTP status}; every attack must be refused.
"""
import datetime
import hashlib
import json
import ssl
import uuid

import httpx

from common.crypto import canonical_json, load_ed25519_private, signed_headers
from common.transfers import transfer_tx_id

KEY = load_ed25519_private("/keys/private/signing-ed25519.pem")
USER = "11111111-0000-4000-8000-000000000001"   # Ana


def payload(amount="1.00", age_minutes=0):
    key = f"tamper-{uuid.uuid4().hex}"
    ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=age_minutes)
    return {"tx_id": str(transfer_tx_id(USER, key)), "idempotency_key": key, "user_id": USER,
            "from_iban": "GS-EU-00000001", "to_iban": "GS-AM-00000001", "amount": amount,
            "ts": ts.isoformat(), "requested_by": "api-1"}


client = httpx.Client(base_url="https://coordinator.global.local:8020",
                      verify=ssl.create_default_context(cafile="/certs/ca.crt"), timeout=10)
results = {}

# 1. Signed for 1.00, amount changed to 9000.00 in transit
p = payload()
body = canonical_json(p)
headers = signed_headers(KEY, "api-1", body)
tampered = canonical_json({**p, "amount": "9000.00"})
results["montante_alterado"] = client.post("/tx", content=tampered, headers=headers).status_code

# 2. Same, but the attacker also recomputes the SHA-256 header (cannot recompute the signature)
results["sha256_recalculado"] = client.post(
    "/tx", content=tampered,
    headers={**headers, "X-Payload-SHA256": hashlib.sha256(tampered).hexdigest()}).status_code

# 3. No signature headers at all
results["sem_assinatura"] = client.post("/tx", content=body, headers={"Content-Type": "application/json"}).status_code

# 4. Signer not in the trusted list
results["assinante_desconhecido"] = client.post("/tx", content=body, headers={**headers, "X-Signer": "intruso"}).status_code

# 5. Validly signed, but captured 10 minutes ago and replayed now
old = canonical_json(payload(age_minutes=10))
results["replay_antigo"] = client.post("/tx", content=old, headers=signed_headers(KEY, "api-1", old)).status_code

print(json.dumps(results))
