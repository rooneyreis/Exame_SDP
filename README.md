# Global-Scale System

Plataforma distribuída de transações financeiras internacionais (Exame Prático de Sistemas Distribuídos e Paralelos — ISUTC, LECC 31).

> Em construção, por fases. Estado atual: **Fase 3 — API + Nginx** concluída.

## Requisitos

- Windows + WSL2 (Ubuntu) + Docker Desktop com integração WSL ativa
- No Ubuntu: `git`, `openssl`, `python3` + `python3-venv`, `make`, `jq`, `curl`
- Repositório dentro do sistema de ficheiros do WSL (`~/global-scale-system`), não em `/mnt/c`

## Arranque rápido

```bash
./scripts/gen-certs.sh   # CA local + certificado TLS por serviço (infra/certs, não versionado)
./scripts/gen-keys.sh    # RS256 (JWT), Ed25519 (assinaturas), AES-256 (dados em repouso) — infra/keys
docker compose up -d     # NFS, 5 nós PostgreSQL, auth, api-1, api-2, nginx
./scripts/seed.sh        # câmbios, 3 contas por shard, staff e 6 clientes
make test                # suite de testes (unitários + integração)
```

## Rede

Rede Docker bridge `globalnet`, subnet `172.28.0.0/24`, IPs fixos. Cada serviço tem também o alias DNS `<nome>.global.local`, que é o nome usado nos certificados TLS (SAN).

| Serviço | IP | Porta |
|---|---|---|
| nginx | 172.28.0.10 | 443 (única exposta no host) |
| api-1 / api-2 | 172.28.0.11 / .12 | 8000 |
| auth | 172.28.0.20 | 8010 |
| coordinator | 172.28.0.30 | 8020 |
| legacy-bank | 172.28.0.40 | 9443 |
| nfs | 172.28.0.50 | 2049 |
| pg-core | 172.28.0.60 | 5432 |
| pg-europa / réplica | 172.28.0.61 / .62 | 5432 |
| pg-america / réplica | 172.28.0.63 / .64 | 5432 |

## Sistema de ficheiros distribuído (NFS v4)

**Solução que funcionou: NFS-Ganesha** (opção 1 de 3), servidor NFS em espaço de utilizador no contentor `nfs`.

- Não depende dos módulos `nfsd` do kernel do WSL2/Docker Desktop, por isso não precisa de `privileged`. Só precisa da capability `DAC_READ_SEARCH`, porque o backend VFS do Ganesha usa `open_by_handle_at()`.
- Só NFS v4: não é preciso `rpcbind`/`mountd`/NLM, os locks fazem parte do protocolo.
- Os outros contentores montam `nfs:/audit` através de um **volume Docker do tipo NFS**. Quem faz o mount é o daemon Docker, por isso os contentores clientes não precisam de privilégios.
- `Graceless = true`: o servidor salta o *grace period* de 90 s após arrancar. Em produção esse período serve para os clientes recuperarem os seus locks depois de um reinício do servidor. Ver limitações.
- Os avisos `DBUS` e `krb5` nos logs do `nfs` são esperados (não usamos D-Bus nem Kerberos).

Validação (`tests/integration/test_phase0_nfs.py`): dois contentores escrevem no mesmo export ao mesmo tempo. Cada um lê o ficheiro do outro e ambos incrementam 200× um contador partilhado com `fcntl.lockf` (lock exclusivo). O resultado é exatamente 400, sem atualizações perdidas.

## Base de dados distribuída (PostgreSQL 16)

| Nó | Conteúdo |
|---|---|
| `pg-core` | BD `auth` (utilizadores, refresh tokens) e BD `coordinator` (log 2PC, eventos, câmbios) |
| `pg-europa` → `pg-europa-replica` | BD `bank` do shard Europa (só IBANs `GS-EU-…`) + réplica streaming |
| `pg-america` → `pg-america-replica` | BD `bank` do shard América (só IBANs `GS-AM-…`) + réplica streaming |

- **Fragmentação horizontal por região**: a regra está no próprio esquema (`CHECK (iban ~ '^GS-EU-[0-9]{8}$')` no shard EU). Uma conta da região errada é recusada pela BD.
- **TLS obrigatório**: `pg_hba.conf` só tem `hostssl`. Qualquer ligação sem TLS é rejeitada (`no encryption`). Os clientes usam `sslmode=verify-full`, que verifica a CA e o nome do servidor (SAN). A replicação também corre sobre TLS (TLS 1.3).
- **2PC**: `max_prepared_transactions = 100` em primários e réplicas.
- **Roles por serviço** com privilégio mínimo: `auth_svc` (só BD auth), `coord_svc`, `api_svc`.
- **Um só entrypoint** (`infra/postgres/entrypoint.sh`) para todos os nós:
  1. copia o certificado do nó com permissões `0600`;
  2. réplica com o diretório vazio → `pg_basebackup -R` do primário;
  3. antigo primário que volta depois de um failover → deteta que o par já é primário e **volta como réplica** (evita split-brain).

### Failover

```bash
docker stop pg-europa
./scripts/failover.sh EU     # pg_promote() na réplica
docker start pg-europa       # volta sozinho como réplica do novo primário
```

Os serviços ligam-se com conninfo multi-host (`host=pg-europa.global.local,pg-europa-replica.global.local target_session_attrs=read-write`): depois da promoção, as novas ligações vão para o novo primário sem mudar configuração. As **transações preparadas** (fase 1 do 2PC) estão no WAL, por isso aparecem em `pg_prepared_xacts` no nó promovido e o coordenador pode concluí-las lá. Na réplica em standby só ficam visíveis depois da promoção.

## Autenticação (serviço `auth`)

Acesso pelo Nginx: `https://localhost` (a CA local valida o certificado: `curl --cacert infra/certs/ca.crt`).

| Método | Endpoint | Quem |
|---|---|---|
| POST | `/auth/register` | público → `PENDENTE_VERIFICACAO` |
| POST | `/auth/login` | público → `access_token` (JWT RS256, 15 min) + `refresh_token` (7 dias) |
| POST | `/auth/refresh` | público: roda o refresh token |
| POST | `/auth/logout` | autenticado |
| GET | `/.well-known/jwks.json` | público: chave pública RS256 |
| GET | `/admin/users?status=…`, `/admin/users/{id}` | operador, admin (o detalhe decifra documento e data de nascimento) |
| POST | `/admin/users/{id}/approve-kyc` | operador: cria a conta no shard (via api) e ativa |
| POST | `/admin/staff` | admin |

Utilizadores de demonstração (`./scripts/seed.sh`):

| Email | Role | Senha |
|---|---|---|
| `admin@globalscale.test` / `operador@…` / `auditor@…` | admin / operador / auditor | `Staff#2026` |
| `ana.silva@`, `bruno.costa@`, `carla.mendes@cliente.test` | cliente EU (`GS-EU-00000001..3`) | `Cliente#2026` |
| `david.smith@`, `emily.johnson@`, `frank.miller@cliente.test` | cliente AM (`GS-AM-00000001..3`) | `Cliente#2026` |

```bash
TOKEN=$(curl -s --cacert infra/certs/ca.crt https://localhost/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"ana.silva@cliente.test","password":"Cliente#2026"}' | jq -r .access_token)
```

Segurança aplicada:
- **Senhas**: Argon2id. O hash corre numa thread (`asyncio.to_thread`) para não bloquear o event loop.
- **Bloqueio**: 5 falhas seguidas → `423` durante 15 min. `SELECT … FOR UPDATE` serializa logins paralelos do mesmo utilizador, para não se contornar o contador.
- **Sem enumeração de utilizadores**: email inexistente e senha errada dão a mesma resposta, e o tempo de resposta é igual (verificação Argon2 contra um hash fictício).
- **JWT RS256** com `kid` (thumbprint RFC 7638). Só o `auth` tem a chave privada. A validação exige `exp`, `iss`, `aud`, `kid` e `alg=RS256` (bloqueia `alg: none`).
- **Refresh tokens**: guardados só como SHA-256. Rodam a cada uso, e um token revogado usado de novo revoga todas as sessões do utilizador (deteção de roubo).
- **Dados em repouso**: `document_id` e `birth_date` cifrados com AES-256-GCM (`nonce || ciphertext || tag`), com o `user_id` como *associated data*. A chave (`infra/keys/private/auth-data.key`) só está montada no contentor `auth`.
- **KYC**: a aprovação cria primeiro a conta (chamada à api com um token de serviço `role=service`, 60 s). Se a api estiver em baixo → `503` e o utilizador continua pendente.

## API (api-1 e api-2 atrás do Nginx)

| Método | Endpoint | Quem |
|---|---|---|
| GET | `/me`, `/accounts` | cliente (contas no shard da sua região) |
| GET | `/accounts/{iban}` | dono, operador |
| GET | `/accounts/{iban}/movements` | dono, operador, auditor |
| POST | `/accounts/{iban}/deposit`, `/withdraw` | operador (transação local no shard) |
| GET | `/fx-rates` | autenticado |
| POST | `/internal/accounts` | `role=service` (chamado pelo auth no KYC; idempotente) |
| GET | `/health` | público: estado dos shards (nó que responde) e chaves JWKS em cache |

- **Validação JWT descentralizada**: cada instância descarrega o JWKS do auth no arranque e a cada 10 min. Se o auth cair, continua a validar com a chave em cache (cenário 07).
- **Routing por região** centralizado em `common/db.py`: o prefixo do IBAN (`GS-EU-`/`GS-AM-`) escolhe o pool do shard; o claim `region` do JWT escolhe o shard das contas do utilizador.
- **Movimentos** têm `origin` (`TRANSFERENCIA`/`DEPOSITO`/`LEVANTAMENTO`): depósitos e levantamentos são transações locais do shard, as transferências passam pelo coordenador (Fase 4).
- **Nginx**: round-robin entre `172.28.0.11` e `172.28.0.12`. `proxy_next_upstream error timeout http_502 http_503`: se uma instância não responde, o pedido é repetido na outra e a falhada fica de fora durante `fail_timeout=10s`. POSTs só são repetidos se nunca chegaram ao backend, por isso um depósito nunca é executado duas vezes. O TLS até aos backends é verificado (`proxy_ssl_verify on`, nome `api.global.local` presente nos dois certificados).
- Header `X-Served-By` mostra que instância respondeu.

## Auditoria (NFS)

Cada nó escreve em `/audit/<AAAA-MM-DD>/<nó>.log` (JSON Lines). Cada linha tem `prev_hash` e `hash = SHA-256(prev_hash + JSON canónico da linha)`: alterar, apagar ou reordenar uma linha parte a cadeia a partir daí (`common/audit.py`, validação na Fase 6).

## Cenários de demonstração

```bash
./scripts/demo/01-registo-login.sh   # registo → KYC → conta no shard certo → login → JWT
./scripts/demo/06-queda-api.sh       # docker stop api-1 → tudo servido pela api-2
./scripts/demo/07-queda-auth.sh      # docker stop auth → tokens existentes continuam válidos
PAUSE=1 ./scripts/demo/06-queda-api.sh   # pausa entre passos (apresentação ao docente)
```

A saída de cada cenário fica em `docs/evidencias/<cenário>.log`.

## Limitações conhecidas (parcial)

- O access token JWT é *stateless*: o logout revoga o refresh token, mas o access token continua válido até expirar (máx. 15 min). Em produção: lista de `jti` revogados ou tokens mais curtos.

- Failover manual (`failover.sh`); em produção, Patroni + etcd. Se os **dois** nós de uma região estiverem em baixo depois de um failover e o antigo primário arrancar primeiro, ele fica primário e o que foi escrito no nó promovido perde-se. É precisamente o problema que um gestor de cluster com consenso resolve.
- Replicação assíncrona: com `docker stop` (paragem limpa) o primário envia todo o WAL à réplica antes de sair. Numa queda abrupta, as últimas transações podem não ter chegado. Replicação síncrona (`synchronous_standby_names`) evitaria isso, à custa de latência.
- `pg-core` não tem réplica neste protótipo.

- Servidor NFS único (ponto único de falha); em produção, GlusterFS/CephFS replicado.
- Em Docker Desktop todos os mounts NFS são feitos pelo mesmo kernel (a VM do Docker, `clientaddr=172.28.0.1`). Os locks são arbitrados pelo servidor (`local_lock=none`), mas num cenário real cada nó seria uma máquina diferente com o seu próprio cliente NFS.
- `Graceless = true` (ver acima).
- Nunca alterar o diretório exportado diretamente no servidor NFS: os clientes têm cache de entradas e ficam com referências obsoletas. Todas as escritas passam pelo protocolo NFS.
