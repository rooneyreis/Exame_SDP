# Requisitos do docente → implementação → evidência

Cada ponto do documento *"Exame prático: o que o docente espera ver"*, com o sítio do código que o implementa e o cenário de demonstração que o prova. As evidências são geradas por `./scripts/demo/run-all.sh` em `docs/evidencias/<cenário>.log`.

| # | O docente espera ver | Como está implementado | Código / configuração | Evidência |
|---|---|---|---|---|
| 1 | **Ambiente de rede e SO**: nós Linux com IPs, portas, DNS local e prova de conectividade | Contentores Linux na rede `globalnet` (172.28.0.0/24) com IP fixo, porta própria e alias DNS `<nó>.global.local` | `docker-compose.yml` (`networks`, `ipv4_address`, `aliases`) | **cenário 00**: SO e kernel de cada nó, IP/porta, resolução DNS de todos os nomes, ligação TCP de api-1 e coordinator a todos os nós |
| 2 | **DFS** (NFS/GlusterFS/HDFS) partilhado entre nós, com escrita/leitura de logs de auditoria e relatórios | NFS v4 (NFS-Ganesha) no nó `nfs`, montado em auth, api-1, api-2 e coordinator. Cada nó escreve o seu log de auditoria encadeado por SHA-256; o relatório diário é um só ficheiro atualizado por vários nós com `fcntl.lockf` | `infra/nfs/`, `common/audit.py`, `common/reports.py` | **cenário 16**: montagens nfs4, ficheiro escrito na api-1 e lido nos outros nós, logs por nó, validação das cadeias e relatório partilhado. Também cenário 05 (adulteração de uma linha no NFS detetada) |
| 3 | **BDD** com sharding por região (nó A e nó B) | PostgreSQL 16: shards Europa (`GS-EU-*`), América (`GS-AM-*`) e África (`GS-AF-*`), cada um com réplica; a regra de fragmentação está no esquema (`CHECK`) e no routing (`common/db.py`) | `infra/postgres/init/shard/`, `common/db.py` | cenário 01 (conta criada no shard certo, consulta direta a cada Postgres), cenário 08 (failover), cenário 14 (shard África) |
| 4 | **Transações distribuídas** (2PC ou Saga) entre contas em nós distintos, com falhas de rede sem perda nem duplicação de saldo | 2PC com log durável e recuperação (*presumed abort*); idempotência por `Idempotency-Key` | `services/coordinator/coordinator_service/logic.py`, `main.py` | cenários 03 (2PC), 04 (idempotência), 09 (shard cai durante o 2PC), 10 (crash do coordenador), 11 (concorrência), **13 (partição de rede)**; `GET /admin/consistency` no fim de cada um |
| 5 | **Documentação técnica**: arquitetura, passos de configuração/execução, evidências | README, relatório em `docs/relatorio/`, guia de instalação, logs das demos | `README.md`, `docs/relatorio/`, `docs/DEPLOY.md` | `docs/evidencias/*.log`, capturas em `docs/evidencias/capturas/` |
| 6 | **Core API** REST (JSON) ou gRPC para transações | FastAPI (Python 3.12), duas instâncias atrás do nginx, OpenAPI em `/docs`. O enunciado dá Node.js/Java/C# como exemplos: a escolha de Python está justificada em `05-linguagem-e-concorrencia.md` | `services/api/` | cenários 01–04, 06 |
| 7 | **Módulo legado noutra linguagem** a simular um banco parceiro | Banco parceiro em **Java 21** (só JDK), ledger de largura fixa estilo COBOL | `legacy-bank/src/` | cenário 03 (ordem aceite e registada no ledger) |
| 8 | **Comunicação entre serviços** em JSON ou XML | api → coordinator em JSON canónico; coordinator (Python) → legado (Java) em XML `<SettlementOrder>` / `<SettlementAck>` | `services/coordinator/coordinator_service/settlement.py`, `legacy-bank/src/Xml.java` | cenário 03; testes `tests/integration/test_phase5_legacy.py` |
| 9 | **TLS/HTTPS** entre API, legado e base de dados (pode ser autoassinado) | CA local + certificado por nó; HTTPS em todos os serviços (incl. o legado Java, keystore PKCS12); Postgres só aceita `hostssl` e os clientes usam `verify-full`; replicação sobre TLS | `scripts/gen-certs.sh`, `infra/postgres/pg_hba.conf`, `infra/nginx/nginx.conf` | **cenário 12**: Postgres sem TLS recusado, certificado de outro nó recusado, 0 ligações sem TLS, HTTP simples recusado no nginx, nas api, no auth, no coordinator e no legado Java, TLS 1.1 recusado |
| 10 | **Autenticação distribuída**: login que gera JWT; outros nós validam o token de forma independente | `auth` é o único com a chave privada RS256; api-1/api-2 descarregam a chave pública (JWKS) e validam localmente cada pedido | `services/auth/`, `common/jwt_auth.py` | cenário 01 (login e claims do JWT), **cenário 07** (auth em baixo: tokens continuam válidos nas duas api; token forjado → 401) |
| 11 | **Integridade dos dados**: SHA-256 ou HMAC anexado ao payload | `X-Payload-SHA256` + assinatura Ed25519 (mais forte que HMAC: não há segredo partilhado) em api → coordinator; `<Sha256>` + `<Signature>` no XML coordinator ↔ legado | `common/crypto.py`, `legacy-bank/src/SettlementCrypto.java` | **cenário 05**: montante alterado, SHA-256 recalculado, sem assinatura, assinante desconhecido e replay → todos recusados |

## Como apresentar ao docente

```bash
docker compose up -d --wait && ./scripts/seed.sh
PAUSE=1 ./scripts/demo/run-all.sh     # 17 cenários (00–16), com pausas entre passos
```

Ordem sugerida para uma apresentação curta: 00 (rede) → 16 (DFS) → 01 (login/JWT, shards) → 03 (2PC + legado XML) → 05 (integridade) → 12 (TLS) → 07 (validação independente do JWT) → 13 (falha de rede no 2PC).
