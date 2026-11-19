#!/usr/bin/env bash
# Manual failover of one region: promotes that region's replica to primary.
# Usage: ./scripts/failover.sh EU|AM
#
# It promotes whichever node of the region is currently a running standby, so it
# also works after roles have already been swapped once. It refuses to promote
# while the other node is still a running primary (that would be split-brain).
# Services need no reconfiguration: their multi-host conninfo
# (target_session_attrs=read-write) finds the new primary on the next connection.
set -euo pipefail

case "${1:-}" in
  EU) NODES=(pg-europa pg-europa-replica) ;;
  AM) NODES=(pg-america pg-america-replica) ;;
  *) echo "Uso: $0 EU|AM" >&2; exit 2 ;;
esac

# Prints t (standby), f (primary) or "down".
role_of() {
  docker exec "$1" psql -U postgres -tAc "SELECT pg_is_in_recovery()" 2>/dev/null || echo down
}

declare -A ROLE
for n in "${NODES[@]}"; do
  ROLE[$n]=$(role_of "$n")
  echo "[failover] $n: $(case ${ROLE[$n]} in t) echo réplica;; f) echo primário;; *) echo 'em baixo';; esac)"
done

for n in "${NODES[@]}"; do
  if [[ "${ROLE[$n]}" == "f" ]]; then
    echo "[failover] RECUSADO: $n ainda é um primário a correr. Pára-o primeiro (docker stop $n)." >&2
    exit 1
  fi
done

TARGET=""
for n in "${NODES[@]}"; do
  [[ "${ROLE[$n]}" == "t" ]] && TARGET=$n
done
if [[ -z "$TARGET" ]]; then
  echo "[failover] ERRO: não há nenhuma réplica a correr para promover." >&2
  exit 1
fi

echo "[failover] A promover $TARGET com pg_promote()..."
docker exec "$TARGET" psql -U postgres -tAc "SELECT pg_promote(wait => true, wait_seconds => 30)" >/dev/null

if [[ "$(role_of "$TARGET")" == "f" ]]; then
  echo "[failover] OK: $TARGET é agora o PRIMÁRIO da região $1."
  echo "[failover] As transações preparadas que estavam no WAL continuam lá:"
  docker exec "$TARGET" psql -U postgres -tAc "SELECT count(*) || ' preparada(s) pendente(s)' FROM pg_prepared_xacts"
  echo "[failover] Quando o nó antigo voltar (docker start), junta-se automaticamente como réplica."
else
  echo "[failover] ERRO: a promoção falhou." >&2
  exit 1
fi
