#!/usr/bin/env bash
# Scenario 05: (a) requests changed after being signed are rejected by the coordinator;
# (b) a line edited in the audit log on the NFS is detected by /admin/audit.
source "$(dirname "$0")/lib.sh"

title "Cenário 05 — Adulteração de mensagens e de logs"

step "1. Ataques ao canal api → coordinator (executados de dentro da rede, no contentor api-1)"
info "o atacante tem um pedido assinado de 1.00 EUR e tenta alterá-lo ou reutilizá-lo:"
RESULT=$(docker exec -i api-1 python - < tests/integration/tamper_client.py | tail -1)
echo "$RESULT" | jq -r 'to_entries[] | "    \(.key): HTTP \(.value)"'
[[ "$RESULT" == '{"montante_alterado": 401, "sha256_recalculado": 401, "sem_assinatura": 401, "assinante_desconhecido": 401, "replay_antigo": 422}' ]] \
  && ok "todos os pedidos adulterados foram rejeitados" || fail "algum ataque passou"
info "evento de auditoria escrito pelo coordenador no NFS:"
docker compose exec -T nfs sh -c "grep ADULTERACAO_DETETADA /audit/$(date -u +%F)/coordinator.log | tail -2" \
  | jq -c '{ts, event, reason}' | sed 's/^/    /'
pause

step "2. Validação da cadeia de hashes da auditoria (antes da adulteração)"
login auditor@globalscale.test "$STAFF_PASSWORD"
api GET /admin/audit
expect 200 "auditoria lida do NFS"
echo "$LAST_BODY" | jq -r '.files | to_entries[] | "    \(.key): \(.value.lines) linhas, ok=\(.value.ok)"'
[[ "$(echo "$LAST_BODY" | jq -r .ok)" == true ]] && ok "todas as cadeias íntegras" || fail "cadeia já estava partida"
pause

step "3. Um intruso com acesso ao NFS altera o montante de uma linha do coordinator.log"
# Edited THROUGH an NFS client (as an attacker on another node would), byte for byte
# (same length, so concurrent appends by the coordinator are not disturbed).
EDIT=$(docker compose --profile nfs-test run --rm --no-deps -T nfs-test-a python - "$(date -u +%F)" <<'PY' 2>/dev/null
import json, re, sys
path = f"/audit/{sys.argv[1]}/coordinator.log"
data = open(path, "rb").read()
m = re.search(rb'"event": "TRANSFERENCIA"[^\n]*?"amount": "(\d)', data)
pos = m.start(1)
old = data[pos:pos + 1]
new = b"9" if old != b"9" else b"8"
with open(path, "r+b") as f:
    f.seek(pos); f.write(new)
line_no = data[:pos].count(b"\n") + 1
print(json.dumps({"pos": pos, "old": old.decode(), "new": new.decode(), "line": line_no}))
PY
)
info "alteração: $(echo "$EDIT" | jq -c .)"
POS=$(echo "$EDIT" | jq -r .pos); OLD=$(echo "$EDIT" | jq -r .old); LINE=$(echo "$EDIT" | jq -r .line)

step "4. O auditor volta a validar"
api GET /admin/audit
echo "$LAST_BODY" | jq '.files["coordinator.log"] | {lines, ok, first_bad_line, reason}' | sed 's/^/    /'
BAD=$(echo "$LAST_BODY" | jq -r '.files["coordinator.log"].first_bad_line')
[[ "$(echo "$LAST_BODY" | jq -r .ok)" == false && "$BAD" == "$LINE" ]] \
  && ok "adulteração detetada exatamente na linha $LINE do coordinator.log" || fail "não detetou"
info "conteúdo da linha adulterada: $(echo "$LAST_BODY" | jq -r '.files["coordinator.log"].bad_content' | cut -c1-160)…"
pause

step "5. Repor o byte original (para a demonstração poder ser repetida)"
docker compose --profile nfs-test run --rm --no-deps -T nfs-test-a python -c "
f = open('/audit/$(date -u +%F)/coordinator.log', 'r+b'); f.seek($POS); f.write(b'$OLD'); f.close()" 2>/dev/null
api GET /admin/audit
[[ "$(echo "$LAST_BODY" | jq -r .ok)" == true ]] && ok "cadeia íntegra de novo" || fail "não repôs"

title "Cenário 05 concluído"
