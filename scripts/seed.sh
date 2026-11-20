#!/usr/bin/env bash
# Seeds demo data. Idempotent (safe to run more than once).
#   Phase 1: FX rates (pg-core/coordinator) and 3 accounts per shard.
#   Phase 2: users (admin, operador, auditor and the 9 clients), created by the auth
#            service itself (Argon2 hashes + AES-GCM encrypted fields need its keys).
# Shards are reached with a multi-host conninfo, so this works after a failover too.
set -euo pipefail
cd "$(dirname "$0")/.."

PSQL=(docker compose run --rm -T pgclient)
TLS="sslmode=verify-full"

./scripts/migrate.sh

echo "[seed] Taxas de câmbio (pg-core / coordinator)"
"${PSQL[@]}" "host=pg-core.global.local dbname=coordinator $TLS" -q -f /sql/seed-coordinator.sql

echo "[seed] Contas do shard Europa (EUR)"
"${PSQL[@]}" "host=pg-europa.global.local,pg-europa-replica.global.local target_session_attrs=read-write dbname=bank $TLS" \
  -v region=EU -v currency=EUR -v uuid_prefix=11111111 -v scale=1 -q -f /sql/seed-shard.sql

echo "[seed] Contas do shard América (USD)"
"${PSQL[@]}" "host=pg-america.global.local,pg-america-replica.global.local target_session_attrs=read-write dbname=bank $TLS" \
  -v region=AM -v currency=USD -v uuid_prefix=22222222 -v scale=1 -q -f /sql/seed-shard.sql

echo "[seed] Contas do shard África (MZN)"
"${PSQL[@]}" "host=pg-africa.global.local,pg-africa-replica.global.local target_session_attrs=read-write dbname=bank $TLS" \
  -v region=AF -v currency=MZN -v uuid_prefix=33333333 -v scale=50 -q -f /sql/seed-shard.sql

echo "[seed] Utilizadores (auth)"
docker compose exec -T auth python -m auth_service.seed

echo "[seed] Concluído."
