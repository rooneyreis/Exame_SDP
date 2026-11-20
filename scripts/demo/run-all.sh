#!/usr/bin/env bash
# Runs every demo scenario in order. Each one saves its output to docs/evidencias/.
#   ./scripts/demo/run-all.sh            -> straight through (also used to validate a clean clone)
#   PAUSE=1 ./scripts/demo/run-all.sh    -> stops between steps, for the presentation
set -euo pipefail
cd "$(dirname "$0")/../.."

SCENARIOS=(
  01-registo-login
  02-transferencia-local
  03-transferencia-2pc
  04-idempotencia
  05-adulteracao
  06-queda-api
  07-queda-auth
  08-queda-shard-failover
  09-queda-durante-2pc
  10-crash-coordenador
  11-concorrencia
  12-tls
  13-particao-rede
)

start=$(date +%s)
declare -a summary
for s in "${SCENARIOS[@]}"; do
  t0=$(date +%s)
  if ./scripts/demo/$s.sh; then
    summary+=("✔ $s ($(( $(date +%s) - t0 ))s)")
  else
    summary+=("✘ $s")
    printf '\n\033[1;31m%s falhou — ver docs/evidencias/%s.log\033[0m\n' "$s" "$s"
    printf '%s\n' "${summary[@]}"
    exit 1
  fi
  if [[ "${PAUSE:-0}" == "1" ]]; then read -rp "  (Enter para o próximo cenário)" _ </dev/tty; fi
done

printf '\n\033[1;36m══════ Resumo (%ss) ══════\033[0m\n' "$(( $(date +%s) - start ))"
printf '  %s\n' "${summary[@]}"
printf '\nEvidências em docs/evidencias/*.log\n'
