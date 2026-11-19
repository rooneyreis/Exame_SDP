# Base de Dados Distribuída e 2PC (rascunho — notas da Fase 1; completar na Fase 4)

## Fragmentação e replicação (Fase 1)

- Fragmentação **horizontal** por região: `pg-europa` guarda só IBANs `GS-EU-…`, `pg-america` só `GS-AM-…`. A regra está no esquema (`CHECK` em `infra/postgres/init/shard/01-init.sh`) e no routing da aplicação (`common/db.py`, Fase 3).
- Porquê por região: localidade dos dados (latência baixa para clientes da mesma região), requisitos legais de residência dos dados e escalabilidade horizontal (mais regiões = mais shards).
- Replicação **streaming física e assíncrona** (WAL) primário → réplica, sobre TLS. A réplica aceita só leituras (`hot_standby`).
- Failover: `pg_promote()` (`scripts/failover.sh`) + conninfo multi-host com `target_session_attrs=read-write` (transparência de falha para os clientes).
- Evidência: `tests/integration/test_phase1_zz_failover.py`. Uma transação **preparada** no primário antes de ele cair aparece em `pg_prepared_xacts` no nó promovido. O PREPARE é escrito no WAL e por isso replicado. Isto liga a replicação à durabilidade da fase 1 do 2PC.

## A desenvolver na Fase 4

- Protocolo 2PC passo a passo com a linha temporal real de `tx_events`.
- ACID: Atomicidade (decisão única no log), Consistência (`CHECK balance >= 0`), Isolamento (`SELECT … FOR UPDATE`, `lock_timeout`), Durabilidade (PREPARE no WAL + log do coordenador).
- 2PC vs. Saga.
