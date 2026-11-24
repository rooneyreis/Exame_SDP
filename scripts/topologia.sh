#!/usr/bin/env bash
# Where each database is right now: its owner node and the node that keeps its copy
# (common/topology.json), and which of the two is the PRIMARY (the other follows it).
#   ./scripts/topologia.sh            -> table
#   ./scripts/topologia.sh EU         -> prints the node:port that is the primary of EU
# The takeover is automatic (supervisor in each Postgres node); this script only reads.
set -euo pipefail
cd "$(dirname "$0")/.."

# cluster  owner:port  copy:port
TOPO=(
  "CORE pg-core:5432 pg-america:5434"
  "EU   pg-europa:5432 pg-america:5433"
  "AM   pg-america:5432 pg-africa:5433"
  "AF   pg-africa:5432 pg-europa:5433"
)

# role NODE PORT -> primário | cópia | em baixo   (docker exec: does not depend on the network)
role() {
  local out
  out=$(docker exec "$1" psql -U postgres -p "$2" -tAc "SELECT pg_is_in_recovery()" 2>/dev/null || true)
  case "$out" in f) echo primário ;; t) echo cópia ;; *) echo "em baixo" ;; esac
}

if [[ -n "${1:-}" ]]; then
  for line in "${TOPO[@]}"; do
    read -r name owner copy <<<"$line"
    [[ "$name" == "$1" ]] || continue
    for loc in "$owner" "$copy"; do
      [[ "$(role "${loc%%:*}" "${loc##*:}")" == primário ]] && { echo "$loc"; exit 0; }
    done
    echo "nenhum"; exit 1
  done
  echo "uso: $0 [CORE|EU|AM|AF]" >&2; exit 2
fi

printf '%-6s %-22s %-12s %-22s %-12s\n' BASE "DONO" "" "CÓPIA" ""
for line in "${TOPO[@]}"; do
  read -r name owner copy <<<"$line"
  printf '%-6s %-22s %-12s %-22s %-12s\n' "$name" "$owner" "$(role "${owner%%:*}" "${owner##*:}")" \
    "$copy" "$(role "${copy%%:*}" "${copy##*:}")"
done
