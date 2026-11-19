"""N concurrent transfers between the same 3 accounts, in both directions (scenario 11).

Checks afterwards, from the API only:
  - every request got a final answer (CONFIRMADA or ABORTADA), none hanging
  - no transfer aborted by lock_timeout (the global lock order prevents distributed deadlocks)
  - money is conserved per currency:  balance_after - balance_before ==
        sum(credits received) - sum(debits sent)   over the CONFIRMED transfers only
Usage: .venv/bin/python scripts/demo/concurrency.py 50
"""
import asyncio
import random
import ssl
import sys
import time
import uuid
from collections import Counter
from decimal import Decimal
from pathlib import Path

import httpx

BASE = "https://localhost"
CA = Path(__file__).resolve().parents[2] / "infra" / "certs" / "ca.crt"
CLIENTS = {
    "GS-EU-00000001": ("ana.silva@cliente.test", "Cliente#2026"),
    "GS-EU-00000002": ("bruno.costa@cliente.test", "Cliente#2026"),
    "GS-AM-00000001": ("david.smith@cliente.test", "Cliente#2026"),
}
ROUTES = [("GS-EU-00000001", "GS-EU-00000002"), ("GS-EU-00000002", "GS-EU-00000001"),   # LOCAL
          ("GS-EU-00000001", "GS-AM-00000001"), ("GS-AM-00000001", "GS-EU-00000001")]   # DISTRIBUIDA


async def login(client, email, password):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def main(n: int) -> int:
    ctx = ssl.create_default_context(cafile=str(CA))
    async with httpx.AsyncClient(base_url=BASE, verify=ctx, timeout=60,
                                 limits=httpx.Limits(max_connections=n)) as client:
        tokens = {iban: await login(client, *cred) for iban, cred in CLIENTS.items()}
        operator = await login(client, "operador@globalscale.test", "Staff#2026")

        async def balances():
            out = {}
            for iban in CLIENTS:
                out[iban] = Decimal((await client.get(f"/accounts/{iban}", headers=operator)).json()["balance"])
            return out

        before = await balances()
        random.seed(42)
        plan = [(random.choice(ROUTES), Decimal(random.randint(100, 2000)) / 100) for _ in range(n)]

        async def one(route, amount):
            src, dst = route
            r = await client.post("/transfers", headers={**tokens[src], "Idempotency-Key": f"conc-{uuid.uuid4()}"},
                                  json={"from_iban": src, "to_iban": dst, "amount": f"{amount:.2f}"})
            return r.status_code, r.json()

        start = time.perf_counter()
        results = await asyncio.gather(*(one(route, amount) for route, amount in plan))
        elapsed = time.perf_counter() - start
        after = await balances()

    states = Counter(body.get("state", f"HTTP {code}") for code, body in results)
    kinds = Counter(body.get("kind") for _, body in results)
    reasons = Counter(body.get("failure_reason") for _, body in results if body.get("state") == "ABORTADA")
    print(f"  {n} transferências em {elapsed:.2f}s  estados={dict(states)}  tipos={dict(kinds)}")
    if reasons:
        print(f"  motivos de abort: {dict(reasons)}")

    expected = {iban: Decimal(0) for iban in CLIENTS}
    for code, body in results:
        if body.get("state") == "CONFIRMADA":
            expected[body["from_iban"]] -= Decimal(body["amount"])
            expected[body["to_iban"]] += Decimal(body["converted_amount"])

    ok = True
    for iban in CLIENTS:
        delta = after[iban] - before[iban]
        good = delta == expected[iban] and after[iban] >= 0
        ok &= good
        print(f"  {iban}: {before[iban]} → {after[iban]}  Δ={delta}  esperado={expected[iban]}  {'✔' if good else '✘'}")
    unfinished = [b for _, b in results if b.get("state") not in ("CONFIRMADA", "ABORTADA")]
    lock_timeouts = sum(1 for r in reasons if r and "lock_timeout" in r)
    print(f"  pendentes={len(unfinished)}  abortadas por lock_timeout/deadlock={lock_timeouts}")
    ok &= not unfinished and lock_timeouts == 0
    print("  ✔ conservação do dinheiro verificada" if ok else "  ✘ FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 50)))
