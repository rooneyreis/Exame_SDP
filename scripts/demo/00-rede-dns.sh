#!/usr/bin/env bash
# Scenario 00: the nodes (Linux containers) have fixed IPs, ports and local DNS names
# (*.global.local), and every node can reach the others over the network.
source "$(dirname "$0")/lib.sh"

title "Cenário 00 — Ambiente de rede e SO: IPs, portas, DNS local e conectividade"

# name|port: every node of globalnet and the port of its service
NODES=(
  "nginx|443" "api-1|8000" "api-2|8000" "auth|8010" "coordinator|8020"
  "legacy-bank|9443" "nfs|2049" "pg-core|5432" "pg-europa|5432" "pg-america|5432" "pg-africa|5432"
)
# the copies kept by each node (ring): reachable on their own ports
COPIES=("pg-europa|5433" "pg-america|5433" "pg-america|5434" "pg-africa|5433")

step "1. Nós Linux: sistema operativo e kernel de cada contentor"
for entry in "${NODES[@]}"; do
  n=${entry%%|*}
  os=$(docker exec "$n" sh -c '. /etc/os-release && echo "$PRETTY_NAME"' 2>/dev/null || echo "?")
  kernel=$(docker exec "$n" uname -sr 2>/dev/null || echo "?")
  printf '    %-20s %-38s %s\n' "$n" "$os" "$kernel"
done
ok "todos os nós são Linux (imagens Debian/Ubuntu/Alpine sobre o mesmo kernel)"
pause

step "2. Rede globalnet: subnet e IP fixo de cada nó"
cmd "docker network inspect gss_globalnet"
docker network inspect gss_globalnet -f '    subnet {{(index .IPAM.Config 0).Subnet}}  driver {{.Driver}}'
for entry in "${NODES[@]}"; do
  n=${entry%%|*}; port=${entry##*|}
  ip=$(docker inspect -f '{{(index .NetworkSettings.Networks "gss_globalnet").IPAddress}}' "$n")
  printf '    %-20s %-14s porta %s\n' "$n" "$ip" "$port"
done
pause

step "3. DNS local: cada nó resolve os nomes *.global.local dos outros (resolvido a partir da api-1)"
cmd "docker exec api-1 getent hosts <nó>.global.local"
for entry in "${NODES[@]}"; do
  n=${entry%%|*}
  r=$(docker exec api-1 getent hosts "$n.global.local" | awk '{print $1}')
  [[ -n "$r" ]] || fail "$n.global.local não resolve"
  printf '    %-32s → %s\n' "$n.global.local" "$r"
done
ok "todos os nomes resolvem pelo DNS interno do Docker (127.0.0.11)"
docker exec api-1 cat /etc/resolv.conf | grep nameserver | sed 's/^/    /'
pause

step "4. Conectividade: ligação TCP da api-1 e do coordinator a cada nó e porta"
CHECK='
import socket, sys
ok = True
for entry in sys.argv[1:]:
    host, port = entry.split("|")
    name = host + ".global.local"
    me = socket.gethostname()
    try:
        s = socket.create_connection((name, int(port)), timeout=3)
        peer = s.getpeername()[0]; s.close()
        print(f"    {me:12s} -> {name:32s} {peer}:{port}  ligado")
    except OSError as e:
        ok = False
        print(f"    {me:12s} -> {name}:{port}  FALHOU ({e})")
sys.exit(0 if ok else 1)
'
for src in api-1 coordinator; do
  docker exec "$src" python -c "$CHECK" "${NODES[@]}" "${COPIES[@]}" || fail "há nós inacessíveis a partir de $src"
done
ok "todos os nós comunicam entre si"
pause

step "5. Do exterior só a porta 443 (nginx) está publicada"
docker ps --format '    {{.Names}}\t{{.Ports}}' | grep -E "0.0.0.0|:::" || true
api GET /health
expect 200 "https://localhost/health responde (via nginx)"

title "Cenário 00 concluído"
