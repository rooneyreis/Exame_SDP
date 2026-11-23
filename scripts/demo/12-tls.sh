#!/usr/bin/env bash
# Scenario 12: every channel requires TLS; plain connections are refused.
source "$(dirname "$0")/lib.sh"

title "Cenário 12 — TLS obrigatório em todos os canais"

step "1. PostgreSQL sem TLS (sslmode=disable) → recusado pelo pg_hba.conf"
for node in pg-core pg-europa pg-america pg-africa; do
  out=$(docker compose run --rm -T pgclient "host=$node.global.local dbname=postgres sslmode=disable" -c "select 1" 2>&1 | grep -o 'no encryption' || true)
  [[ "$out" == "no encryption" ]] && ok "$node: ligação sem TLS rejeitada (\"no encryption\")" || fail "$node aceitou sem TLS"
done

step "2. PostgreSQL com TLS mas a apontar para o servidor errado → certificado não corresponde ao nome"
out=$(docker compose run --rm -T pgclient "host=pg-europa.global.local hostaddr=172.28.0.63 dbname=postgres sslmode=verify-full" -c "select 1" 2>&1 || true)
echo "$out" | grep -q "does not match host name" && ok "verify-full detetou o servidor falso" || fail "não verificou o nome"

step "3. Todas as ligações ativas aos Postgres estão cifradas"
docker exec pg-europa psql -U postgres -c "SELECT a.usename, a.application_name, s.ssl, s.version, s.cipher
  FROM pg_stat_ssl s JOIN pg_stat_activity a USING (pid) WHERE a.client_addr IS NOT NULL ORDER BY 1,2" | sed 's/^/    /'
plain=$(docker exec pg-europa psql -U postgres -tAc "SELECT count(*) FROM pg_stat_ssl s JOIN pg_stat_activity a USING (pid) WHERE a.client_addr IS NOT NULL AND NOT s.ssl")
[[ "$plain" == 0 ]] && ok "0 ligações de rede sem TLS" || fail "$plain ligações sem TLS"
pause

step "4. HTTP simples à porta 80 → recusado ou redirecionado para HTTPS (nunca serve dados)"
cmd "curl http://localhost/health"
http_code=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 3 http://localhost/health || true)
case "$http_code" in
  000*) ok "ligação recusada (só existe HTTPS 443)" ;;
  "301 https://"*) ok "HTTP $http_code — redirecionado para HTTPS, sem conteúdo" ;;
  *) fail "HTTP respondeu com conteúdo: $http_code" ;;
esac

step "5. HTTP simples na porta HTTPS → o nginx recusa"
cmd "curl http://localhost:443/health"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://localhost:443/health || true)
[[ "$code" == 400 ]] && ok "HTTP $code: \"The plain HTTP request was sent to HTTPS port\"" || fail "resposta inesperada $code"

step "6. Dentro da rede: HTTP simples diretamente a uma api → recusado (Uvicorn só fala TLS)"
docker exec api-1 python -c "
import urllib.request
try:
    urllib.request.urlopen('http://api-2.global.local:8000/health', timeout=3); print('ACEITE')
except Exception as e:
    print('recusado:', type(e).__name__)" | sed 's/^/    /' | tee /tmp/tls12.out
grep -q recusado /tmp/tls12.out && ok "api-2 recusou HTTP sem TLS" || fail "api-2 aceitou HTTP"

step "7. Serviços internos (auth, coordinator, banco legado Java): só TLS, verificado pela CA local"
cmd "docker exec coordinator python  (HTTP simples e depois HTTPS a cada serviço)"
docker exec coordinator python -c "
import socket, ssl, urllib.request
ctx = ssl.create_default_context(cafile='/certs/ca.crt')
for name, port in [('auth', 8010), ('coordinator', 8020), ('legacy-bank', 9443)]:
    host = name + '.global.local'
    try:
        urllib.request.urlopen(f'http://{host}:{port}/', timeout=3); plain = 'ACEITE'
    except Exception as e:
        plain = 'recusado (' + type(e).__name__ + ')'
    with socket.create_connection((host, port), timeout=3) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as s:
            cn = dict(x[0] for x in s.getpeercert()['subject'])['commonName']
            print(f'    {host:28s} HTTP: {plain:28s} TLS: {s.version()} {s.cipher()[0]}  cert CN={cn}')
" | tee /tmp/tls12b.out
! grep -q ACEITE /tmp/tls12b.out && ok "nenhum serviço interno aceita texto simples; o legado Java fala TLS com certificado da CA" \
  || fail "um serviço interno aceitou HTTP simples"
pause

step "8. Protocolos e cadeia de certificados no nginx"
cmd "openssl s_client -connect localhost:443 -CAfile $CA"
echo | openssl s_client -connect localhost:443 -servername localhost -CAfile "$CA" 2>/dev/null \
  | grep -E "^(subject|issuer)=|Protocol|Verify return code" | sed 's/^ *//; s/^/    /'
if echo | openssl s_client -connect localhost:443 -tls1_1 -CAfile "$CA" >/dev/null 2>&1; then
  fail "TLS 1.1 aceite"
else
  ok "TLS 1.1 recusado (mínimo TLS 1.2)"
fi

title "Cenário 12 concluído"
