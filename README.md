# Global-Scale System

Plataforma distribuída de transações financeiras internacionais (Exame Prático de Sistemas Distribuídos e Paralelos — ISUTC, LECC 31).

> Em construção, por fases. Estado atual: **Fase 1 — PostgreSQL** concluída.

## Requisitos

- Windows + WSL2 (Ubuntu) + Docker Desktop com integração WSL ativa
- No Ubuntu: `git`, `openssl`, `python3` + `python3-venv`, `make`, `jq`, `curl`
- Repositório dentro do sistema de ficheiros do WSL (`~/global-scale-system`), não em `/mnt/c`

## Arranque rápido

```bash
./scripts/gen-certs.sh   # CA local + certificado TLS por serviço (infra/certs, não versionado)
./scripts/gen-keys.sh    # RS256 (JWT), Ed25519 (assinaturas), AES-256 (dados em repouso) — infra/keys
docker compose up -d     # NFS + 5 nós PostgreSQL
./scripts/seed.sh        # taxas de câmbio + 3 contas por shard
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

## Limitações conhecidas (parcial)

- Failover manual (`failover.sh`); em produção, Patroni + etcd. Se os **dois** nós de uma região estiverem em baixo depois de um failover e o antigo primário arrancar primeiro, ele fica primário e o que foi escrito no nó promovido perde-se. É precisamente o problema que um gestor de cluster com consenso resolve.
- Replicação assíncrona: com `docker stop` (paragem limpa) o primário envia todo o WAL à réplica antes de sair. Numa queda abrupta, as últimas transações podem não ter chegado. Replicação síncrona (`synchronous_standby_names`) evitaria isso, à custa de latência.
- `pg-core` não tem réplica neste protótipo.

- Servidor NFS único (ponto único de falha); em produção, GlusterFS/CephFS replicado.
- Em Docker Desktop todos os mounts NFS são feitos pelo mesmo kernel (a VM do Docker, `clientaddr=172.28.0.1`). Os locks são arbitrados pelo servidor (`local_lock=none`), mas num cenário real cada nó seria uma máquina diferente com o seu próprio cliente NFS.
- `Graceless = true` (ver acima).
