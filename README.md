# Global-Scale System

Plataforma distribuída de transações financeiras internacionais (Exame Prático de Sistemas Distribuídos e Paralelos — ISUTC, LECC 31).

> Em construção, por fases. Estado atual: **Fase 0 — fundações** concluída.

## Requisitos

- Windows + WSL2 (Ubuntu) + Docker Desktop com integração WSL ativa
- No Ubuntu: `git`, `openssl`, `python3` + `python3-venv`, `make`, `jq`, `curl`
- Repositório dentro do sistema de ficheiros do WSL (`~/global-scale-system`), não em `/mnt/c`

## Arranque rápido

```bash
./scripts/gen-certs.sh   # CA local + certificado TLS por serviço (infra/certs, não versionado)
./scripts/gen-keys.sh    # RS256 (JWT), Ed25519 (assinaturas), AES-256 (dados em repouso) — infra/keys
docker compose up -d     # por agora: só o servidor NFS
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

## Limitações conhecidas (parcial)

- Servidor NFS único (ponto único de falha); em produção, GlusterFS/CephFS replicado.
- Em Docker Desktop todos os mounts NFS são feitos pelo mesmo kernel (a VM do Docker, `clientaddr=172.28.0.1`). Os locks são arbitrados pelo servidor (`local_lock=none`), mas num cenário real cada nó seria uma máquina diferente com o seu próprio cliente NFS.
- `Graceless = true` (ver acima).
