#!/usr/bin/env bash
# Scenario 14: distributed file system (NFS v4). Several nodes mount the same export;
# a file written on one node is read on the others; the audit logs and the shared daily
# report are written by every node and read back by the auditor.
source "$(dirname "$0")/lib.sh"

title "Cenário 16 — Sistema de ficheiros distribuído (NFS v4): auditoria e relatórios partilhados"
DAY=$(date -u +%F)

step "1. O export nfs:/audit está montado (NFS v4) em vários nós"
for n in auth api-1 api-2 coordinator; do
  m=$(docker exec "$n" sh -c "grep ' /audit ' /proc/mounts" | awk '{print $1, $3}')
  [[ "$m" == *nfs4* ]] || fail "$n não tem /audit montado por NFS v4"
  printf '    %-12s /audit  ←  %s\n' "$n" "$m"
done
ok "4 nós veem o mesmo sistema de ficheiros, servido pelo nó nfs (172.28.0.50)"
pause

step "2. Escrever num nó e ler nos outros (transparência de localização)"
FILE="/audit/demo-dfs/$(date -u +%H%M%S)-api-1.txt"
cmd "docker exec api-1  → escreve $FILE"
docker exec api-1 sh -c "mkdir -p /audit/demo-dfs && echo \"escrito por \$(hostname) às \$(date -u +%T)\" > $FILE"
for n in api-2 coordinator auth; do
  content=$(docker exec "$n" cat "$FILE") || fail "$n não leu o ficheiro"
  printf '    %-12s lê: %s\n' "$n" "$content"
done
info "no disco do servidor NFS:"
docker exec nfs ls -l "$FILE" | sed 's/^/    /'
docker exec api-1 rm -f "$FILE"
ok "o mesmo ficheiro é visível em todos os nós"
pause

step "3. Gerar atividade: um depósito (escreve no log de auditoria e no relatório partilhado)"
login operador@globalscale.test "$STAFF_PASSWORD"
api POST /accounts/GS-EU-00000002/deposit '{"amount":"10.00","description":"demo DFS"}'
expect 200 "depósito registado"
info "servido por $LAST_SERVED, que escreveu no NFS com lock exclusivo:"
docker logs "$LAST_SERVED" 2>&1 | grep -E "lock NFS (adquirido|libertado)" | tail -2 | sed 's/^/    /'
api POST /accounts/GS-EU-00000002/withdraw '{"amount":"10.00","description":"demo DFS (reposição)"}' >/dev/null
info "(saldo reposto com um levantamento de 10.00)"
pause

step "4. Logs de auditoria: um ficheiro por nó, todos no mesmo diretório partilhado"
cmd "ls -l /audit/$DAY/"
docker exec nfs ls -l "/audit/$DAY/" | sed 's/^/    /'
info "última linha do log da api, lida a partir do coordinator (outro nó):"
docker exec coordinator sh -c "cat /audit/$DAY/api-*.log | tail -1" \
  | jq -c '{ts, node, event, prev_hash: (.prev_hash[0:16] + "…"), hash: (.hash[0:16] + "…")}' | sed 's/^/    /'
pause

step "5. O auditor lê todos os logs do NFS e valida as cadeias de hashes SHA-256"
login auditor@globalscale.test "$STAFF_PASSWORD"
api GET "/admin/audit?date=$DAY"
expect 200 "auditoria lida do NFS"
echo "$LAST_BODY" | jq -r '.files | to_entries[] | "    \(.key): \(.value.lines) linhas, íntegra=\(.value.ok)"'
pause

step "6. Relatório diário partilhado /audit/reports/$DAY.json (atualizado pela api-1, api-2 e coordinator)"
api GET "/admin/reports?date=$DAY"
expect 200 "relatório lido do NFS"
show '.'
docker exec nfs ls -l "/audit/reports/$DAY.json" | sed 's/^/    /'

title "Cenário 16 concluído"
