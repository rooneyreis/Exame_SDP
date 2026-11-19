"""Demo users (run by scripts/seed.sh: docker compose exec auth python -m auth_service.seed).

The client ids match the accounts seeded in the shards (scripts/sql/seed-shard.sql).
Idempotent: users that already exist are left untouched.
"""
import asyncio
import uuid

import psycopg
from argon2 import PasswordHasher

from common.crypto import encrypt_field

from .config import settings

STAFF_PASSWORD = "Staff#2026"
CLIENT_PASSWORD = "Cliente#2026"

STAFF = [
    ("00000000-0000-4000-8000-000000000001", "Administrador", "admin@globalscale.test", "+258840000001", "admin"),
    ("00000000-0000-4000-8000-000000000002", "Olga Operadora", "operador@globalscale.test", "+258840000002", "operador"),
    ("00000000-0000-4000-8000-000000000003", "Artur Auditor", "auditor@globalscale.test", "+258840000003", "auditor"),
]

CLIENTS = [
    ("11111111-0000-4000-8000-000000000001", "Ana Silva", "ana.silva@cliente.test", "+351910000001", "EU", "PT1234567", "1990-04-12"),
    ("11111111-0000-4000-8000-000000000002", "Bruno Costa", "bruno.costa@cliente.test", "+351910000002", "EU", "PT2345678", "1985-09-30"),
    ("11111111-0000-4000-8000-000000000003", "Carla Mendes", "carla.mendes@cliente.test", "+351910000003", "EU", "PT3456789", "1999-01-05"),
    ("22222222-0000-4000-8000-000000000001", "David Smith", "david.smith@cliente.test", "+12025550001", "AM", "US1234567", "1988-07-21"),
    ("22222222-0000-4000-8000-000000000002", "Emily Johnson", "emily.johnson@cliente.test", "+12025550002", "AM", "US2345678", "1993-11-02"),
    ("22222222-0000-4000-8000-000000000003", "Frank Miller", "frank.miller@cliente.test", "+12025550003", "AM", "US3456789", "1979-03-15"),
]


async def main() -> None:
    hasher = PasswordHasher()
    data_key = settings.data_key.read_bytes()
    staff_hash = hasher.hash(STAFF_PASSWORD)
    client_hash = hasher.hash(CLIENT_PASSWORD)

    async with await psycopg.AsyncConnection.connect(settings.db_dsn) as conn:
        for uid, name, email, phone, role in STAFF:
            cur = await conn.execute(
                """INSERT INTO users (id, full_name, email, phone, password_hash, region, role, status)
                   VALUES (%s, %s, %s, %s, %s, 'EU', %s, 'ATIVA') ON CONFLICT DO NOTHING""",
                (uid, name, email, phone, staff_hash, role))
            print(f"[seed] {role:8} {email:32} {'criado' if cur.rowcount else 'já existe'}")
        for uid, name, email, phone, region, doc, birth in CLIENTS:
            aad = str(uuid.UUID(uid)).encode()
            cur = await conn.execute(
                """INSERT INTO users (id, full_name, email, phone, password_hash, region,
                                      document_id_enc, birth_date_enc, role, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'cliente', 'ATIVA') ON CONFLICT DO NOTHING""",
                (uid, name, email, phone, client_hash, region,
                 encrypt_field(data_key, doc, aad), encrypt_field(data_key, birth, aad)))
            print(f"[seed] cliente  {email:32} {'criado' if cur.rowcount else 'já existe'} ({region})")
    print(f"[seed] senhas de demonstração: staff={STAFF_PASSWORD} clientes={CLIENT_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
