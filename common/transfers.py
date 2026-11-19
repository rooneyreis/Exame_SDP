"""Transfer identifiers shared by api and coordinator."""
import uuid

# Fixed namespace: tx_id = uuid5(namespace, "<user_id>:<Idempotency-Key>").
# The api computes it before calling the coordinator, so the client knows its tx_id
# even if the coordinator dies in the middle of the transaction (scenario 10).
TX_NAMESPACE = uuid.UUID("5c6a3e0e-2f3b-4b1e-9d3a-6c1f0b9a7e21")


def transfer_tx_id(user_id: str, idempotency_key: str) -> uuid.UUID:
    return uuid.uuid5(TX_NAMESPACE, f"{user_id}:{idempotency_key}")
