#!/usr/bin/env bash
# Seeds demo data. Idempotent (safe to run more than once).
#   Phase 1: FX rates (pg-core/coordinator) and 3 accounts per shard.
#   Phase 2 adds the users (admin, operador, auditor and the 6 clients).
# Shards are reached with a multi-host conninfo, so this works after a failover too.
set -euo pipefail
cd "$(dirname "$0")/.."

PSQL=(docker compose run --rm -T pgclient)
TLS="sslmode=verify-full"

echo "[seed] Taxas de câmbio (pg-core / coordinator)"
"${PSQL[@]}" "host=pg-core.global.local dbname=coordinator $TLS" -q -f /sql/seed-coordinator.sql

echo "[seed] Contas do shard Europa (EUR)"
"${PSQL[@]}" "host=pg-europa.global.local,pg-europa-replica.global.local target_session_attrs=read-write dbname=bank $TLS" \
  -v region=EU -v currency=EUR -v uuid_prefix=11111111 -q -f /sql/seed-shard.sql

echo "[seed] Contas do shard América (USD)"
"${PSQL[@]}" "host=pg-america.global.local,pg-america-replica.global.local target_session_attrs=read-write dbname=bank $TLS" \
  -v region=AM -v currency=USD -v uuid_prefix=22222222 -q -f /sql/seed-shard.sql

echo "[seed] Concluído."
