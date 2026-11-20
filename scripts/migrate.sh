#!/usr/bin/env bash
# Aplica as migrações de esquema (infra/postgres/migrations/<bd>/*.sql) por ordem, uma única vez
# cada (registadas em schema_migrations). Idempotente: pode ser corrido sempre (o seed.sh chama-o).
set -euo pipefail
cd "$(dirname "$0")/.."

PSQL=(docker compose run --rm -T pgclient)

for db in auth coordinator; do
  conn="host=pg-core.global.local dbname=$db sslmode=verify-full"
  "${PSQL[@]}" "$conn" -q -c "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())" 2>/dev/null
  for file in infra/postgres/migrations/$db/*.sql; do
    [[ -e "$file" ]] || continue
    name=$(basename "$file")
    done_already=$("${PSQL[@]}" "$conn" -tAc "SELECT 1 FROM schema_migrations WHERE name = '$name'" 2>/dev/null)
    if [[ "$done_already" == "1" ]]; then
      continue
    fi
    echo "[migrate] $db: $name"
    # A migração e o registo na tabela correm na mesma transação: ou tudo, ou nada.
    { echo "BEGIN;"; cat "$file"; echo "RESET ROLE; INSERT INTO schema_migrations (name) VALUES ('$name'); COMMIT;"; } \
      | "${PSQL[@]}" "$conn" -q -f - 2>/dev/null
  done
done
# Base de dados "bank" de cada shard (conninfo multi-host: funciona também depois de um failover).
declare -A SHARD=( [EU]=pg-europa [AM]=pg-america [AF]=pg-africa )
IFS=',' read -ra REGION_LIST <<< "${GSS_REGIONS:-EU,AM,AF}"
for region in "${REGION_LIST[@]}"; do
  node=${SHARD[$region]}
  conn="host=$node.global.local,$node-replica.global.local target_session_attrs=read-write dbname=bank sslmode=verify-full"
  "${PSQL[@]}" "$conn" -q -c "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())" 2>/dev/null
  for file in infra/postgres/migrations/bank/*.sql; do
    [[ -e "$file" ]] || continue
    name=$(basename "$file")
    done_already=$("${PSQL[@]}" "$conn" -tAc "SELECT 1 FROM schema_migrations WHERE name = '$name'" 2>/dev/null)
    [[ "$done_already" == "1" ]] && continue
    echo "[migrate] bank@$region: $name"
    { echo "BEGIN;"; cat "$file"; echo "INSERT INTO schema_migrations (name) VALUES ('$name'); COMMIT;"; } \
      | "${PSQL[@]}" "$conn" -q -f - 2>/dev/null
  done
done
echo "[migrate] esquema atualizado"
