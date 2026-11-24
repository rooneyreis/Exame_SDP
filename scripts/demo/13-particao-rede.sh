#!/usr/bin/env bash
# Scenario 13: NETWORK failure (pg-america keeps running, but nobody can reach it):
#   - pg-america sees no other node: it fences itself (read-only), never a second primary;
#   - the copy of America on pg-africa takes over its role.
#   A) partition AFTER both shards prepared -> decision COMMIT is durable -> the recovery
#      loop commits on the copy (the prepared transaction is there): money is not lost.
#   B) partition BEFORE America prepares -> America does not answer -> PENDENTE (Europa
#      rolled back, money never leaves) -> completed on the copy once it took over.
# When the network comes back, pg-america re-syncs from the copy and takes its role back.
source "$(dirname "$0")/lib.sh"

NET=gss_globalnet
cut_network()     { cmd "docker network disconnect $NET pg-america"; docker network disconnect "$NET" pg-america; ok "pg-america isolado da rede (o processo continua vivo)"; }
restore_network() { cmd "docker network connect --ip 172.28.0.63 --alias pg-america.global.local $NET pg-america"
                    docker network connect --ip 172.28.0.63 --alias pg-america.global.local "$NET" pg-america; ok "rede reposta"; }
trap 'docker network connect --ip 172.28.0.63 --alias pg-america.global.local "$NET" pg-america 2>/dev/null || true' EXIT

title "Cenário 13 — Partição de rede durante o 2PC"
login carla.mendes@cliente.test "$CLIENT_PASSWORD"
FROM=GS-EU-00000003; TO=GS-AM-00000001

# ------------------------------------------------------------------------- A
step "A1. Partição DEPOIS do PREPARE: pausa de 15 s antes da decisão"
chaos '{"pause_after_prepare": 15}'
B_FROM=$(balance $FROM); B_TO=$(balance $TO)
OUT=$(mktemp)
curl -s --cacert "$CA" -X POST "$BASE/transfers" -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -H "Idempotency-Key: demo13a-$(date +%s%N)" -d "{\"from_iban\":\"$FROM\",\"to_iban\":\"$TO\",\"amount\":\"30.00\"}" \
  -w '\n%{http_code}' > "$OUT" &
CURL_PID=$!
sleep 4
prepared_xacts
cut_network
wait $CURL_PID
LAST_STATUS=$(tail -1 "$OUT"); LAST_BODY=$(head -n -1 "$OUT")
TX=$(echo "$LAST_BODY" | jq -r .tx_id)
info "resposta: HTTP $LAST_STATUS  state=$(echo "$LAST_BODY" | jq -r .state)"
timeline
state=$(echo "$LAST_BODY" | jq -r .state)
[[ "$state" == DECISAO_COMMIT || "$state" == CONFIRMADA ]] && ok "decisão COMMIT gravada" || fail "esperava DECISAO_COMMIT"
info "pg-america isolado: não vê nenhum outro nó, por isso fica só de leitura (nunca dois primários):"
docker logs pg-america 2>&1 | grep -E "supervisor pg-america/AM.*ISOLADO" | tail -1 | sed 's/^/    /'
SECS=$(wait_role pg-africa 5433 f 40) || fail "a cópia da América não assumiu o papel"
ok "a cópia da América (pg-africa:5433) assumiu o papel"
pause

step "A2. O recovery loop conclui o COMMIT na cópia, ainda com a rede cortada"
wait_tx_state "$TX" CONFIRMADA 60 || fail "não concluiu"
timeline
restore_network
info "rede reposta: pg-america sincroniza-se a partir da cópia e retoma o seu papel..."
wait_all_home || fail "a topologia não voltou ao normal"
topology
A_FROM=$(balance $FROM); A_TO=$(balance $TO)
info "$FROM: $B_FROM → $A_FROM EUR    $TO: $B_TO → $A_TO USD"
decimal_true "D('$B_FROM') - 30 == D('$A_FROM') and D('$B_TO') + D('32.40') == D('$A_TO')" && ok "−30.00 EUR / +32.40 USD: o dinheiro saiu e entrou" || fail "saldos errados"
pause

# ------------------------------------------------------------------------- B
step "B1. Partição ANTES do PREPARE da América: pausa de 8 s antes da fase 1"
chaos '{"off": true}'
chaos '{"pause_before_prepare": 8}'
B_FROM=$(balance $FROM)
curl -s --cacert "$CA" -X POST "$BASE/transfers" -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -H "Idempotency-Key: demo13b-$(date +%s%N)" -d "{\"from_iban\":\"$FROM\",\"to_iban\":\"$TO\",\"amount\":\"40.00\"}" \
  -w '\n%{http_code}' > "$OUT" &
CURL_PID=$!
sleep 3
cut_network
wait $CURL_PID
LAST_STATUS=$(tail -1 "$OUT"); LAST_BODY=$(head -n -1 "$OUT")
info "resposta: HTTP $LAST_STATUS  state=$(echo "$LAST_BODY" | jq -r .state)"
timeline
TX=$(echo "$LAST_BODY" | jq -r .tx_id)
case "$(echo "$LAST_BODY" | jq -r .state)" in
  PENDENTE)
    ok "a América ainda não respondia → PENDENTE (não abortada); a Europa fez ROLLBACK"
    decimal_true "D('$B_FROM') == D('$(balance $FROM)')" && ok "saldo de $FROM inalterado enquanto está pendente: o dinheiro não saiu" || fail "dinheiro saiu!" ;;
  CONFIRMADA) ok "a cópia da América já tinha assumido o papel: transferência concluída nela" ;;
  *) fail "estado inesperado" ;;
esac
pause

step "B2. A transferência é concluída na cópia da América, ainda com a rede cortada"
login auditor@globalscale.test "$STAFF_PASSWORD"
wait_tx_state "$TX" CONFIRMADA 90 || fail "a transferência pendente não foi concluída"
ok "CONFIRMADA na cópia (pg-africa:5433)"
timeline
restore_network
wait_all_home || fail "a topologia não voltou ao normal"
decimal_true "D('$B_FROM') - 40 == D('$(balance $FROM)')" && ok "−40.00 EUR debitados uma única vez" || fail "saldo errado"
pause

step "C. Verificação final: cada base de volta ao seu nó"
chaos '{"off": true}'
topology
prepared_xacts
check_consistency

title "Cenário 13 concluído"
