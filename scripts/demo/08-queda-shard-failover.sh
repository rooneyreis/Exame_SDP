#!/usr/bin/env bash
# Scenario 08: the primary of the Europa shard goes down -> failover.sh promotes the replica
# -> EU transfers work again WITHOUT changing any configuration (multi-host conninfo).
# At the end the original topology is restored (failback).
source "$(dirname "$0")/lib.sh"

title "Cenário 08 — Queda do primário de um shard e failover"
show_db_roles() {
  with_user admin@globalscale.test "$STAFF_PASSWORD" GET /admin/status >/dev/null
  echo "$LAST_BODY" | jq -r '.databases | to_entries[] | select(.key | startswith("pg-europa")) |
    "    \(.key): \(if .value.up then .value.role + " (réplicas a receber: \(.value.replicas_streaming))" else "EM BAIXO" end)"'
}

step "1. Situação inicial"
show_db_roles
login ana.silva@cliente.test "$CLIENT_PASSWORD"
transfer GS-EU-00000001 GS-EU-00000002 1.00 "demo08a-$(date +%s%N)"
expect 201 "transferência EU → EU funciona"
pause

step "2. Derrubar o primário pg-europa"
cmd "docker stop pg-europa"; docker stop pg-europa >/dev/null
show_db_roles
transfer GS-EU-00000001 GS-EU-00000002 1.00 "demo08b-$(date +%s%N)"
info "durante a falha: HTTP $LAST_STATUS — $(echo "$LAST_BODY" | jq -r '.detail // .failure_reason // .state')"
[[ "$LAST_STATUS" != 201 ]] && ok "sem primário na Europa não há escritas (a réplica só aceita leituras)" || fail "não devia funcionar"
api GET /accounts
expect 200 "leituras continuam a funcionar a partir da réplica (target_session_attrs=any)"
show '[.[] | {iban, balance}]'
pause

step "3. Failover: promover a réplica"
cmd "./scripts/failover.sh EU"
./scripts/failover.sh EU | sed 's/^/    /'
show_db_roles
pause

step "4. As transferências voltam a funcionar, sem mudar configuração nenhuma"
info "(os serviços ligam-se com host=pg-europa…,pg-europa-replica… target_session_attrs=read-write)"
transfer GS-EU-00000001 GS-EU-00000002 1.00 "demo08c-$(date +%s%N)"
expect 201 "LOCAL EU → EU no novo primário"
transfer GS-EU-00000001 GS-AM-00000002 1.00 "demo08d-$(date +%s%N)"
expect 201 "DISTRIBUIDA EU → AM (2PC) no novo primário"
api GET /health
info "a api liga-se agora a: $(echo "$LAST_BODY" | jq -r .components.shard_EU.node) (pg-europa-replica = 172.28.0.62)"
pause

step "5. O antigo primário volta e junta-se sozinho como réplica (sem split-brain)"
cmd "docker start pg-europa"; docker start pg-europa >/dev/null
for _ in $(seq 1 60); do
  [[ "$(docker exec pg-europa psql -U postgres -tAc 'select pg_is_in_recovery()' 2>/dev/null)" == t ]] && break; sleep 2
done
docker logs pg-europa 2>&1 | grep pg-entrypoint | tail -3 | sed 's/^/    /'
show_db_roles
check_consistency
pause

step "6. Repor a topologia original (failback)"
docker stop pg-europa-replica >/dev/null
./scripts/failover.sh EU >/dev/null
docker start pg-europa-replica >/dev/null
for _ in $(seq 1 60); do
  [[ "$(docker exec pg-europa-replica psql -U postgres -tAc 'select pg_is_in_recovery()' 2>/dev/null)" == t ]] && break; sleep 2
done
show_db_roles
[[ "$(docker exec pg-europa psql -U postgres -tAc 'select pg_is_in_recovery()')" == f ]] && ok "pg-europa é de novo o primário" || fail "failback falhou"

title "Cenário 08 concluído"
