# Base de Dados Distribuída e Transações Distribuídas (rascunho)

## 1. Fragmentação e replicação

- Fragmentação **horizontal** por região: `pg-europa` guarda só IBANs `GS-EU-…`, `pg-america` só `GS-AM-…`. A regra está no esquema (`CHECK` em `infra/postgres/init/shard/01-init.sh`) e num único sítio da aplicação (`common/db.py`).
- Porquê por região: localidade dos dados (latência baixa para os clientes da região), residência legal dos dados, escalabilidade horizontal (mais regiões = mais shards).
- Replicação **em anel**: cada nó guarda a cópia da base de outro nó (Europa → pg-america, América → pg-africa, África → pg-europa, pg-core → pg-america). Não há contentores só de réplica.
- Replicação **streaming física e síncrona** (`synchronous_commit = remote_apply`), sobre TLS: uma transação só é confirmada quando já está aplicada na cópia. A cópia é só de leitura (`hot_standby`) enquanto o dono está vivo.
- **Troca automática**: o supervisor de cada nó (`infra/postgres/supervisor.py`) promove a cópia (`pg_promote()`) ~6 s depois de o dono desaparecer. Quando o dono volta, sincroniza-se (`pg_basebackup`) e a cópia devolve-lhe o papel (switchover). Os serviços usam conninfo multi-host com `target_session_attrs=read-write` e seguem a base sozinhos.
- **Sem split-brain**: a cópia só assume se ainda vir outro nó (testemunha) e se estava em dia; um primário isolado (não vê ninguém) fica só de leitura; entre dois primários ganha a timeline mais recente.
- As transações **preparadas** estão no WAL e, com replicação síncrona, já estão na cópia quando o `PREPARE` responde: o coordenador conclui-as no nó que assumiu (`tests/integration/test_phase1_zz_failover.py`, cenário 09).

## 2. O problema

Uma transferência EU → AM altera duas bases de dados independentes. Sem coordenação, uma falha entre o débito e o crédito deixava dinheiro a sair de uma conta sem entrar na outra. Nenhum dos dois PostgreSQL sabe da existência do outro.

## 3. Two-Phase Commit implementado (`services/coordinator/coordinator_service/main.py`)

Linha temporal real (cenário 03, `docs/evidencias/03-transferencia-2pc.log`):

```
23:23:56.458  INICIADA          log: a transação existe (commit no pg-core)
23:23:56.463  PREPARANDO        log: vamos começar a fase 1
23:23:56.484  PREPARADO_EU      pg-europa: BEGIN; SELECT … FOR UPDATE; UPDATE; INSERT; PREPARE TRANSACTION → voto SIM
23:23:56.504  PREPARADO_AM      pg-america: idem → voto SIM
23:23:56.509  DECISAO_COMMIT    log: decisão gravada (commit)  ← PONTO DE DECISÃO
23:23:56.513  COMMIT_EU         pg-europa: COMMIT PREPARED
23:23:56.518  COMMIT_AM         pg-america: COMMIT PREPARED
23:23:56.523  CONFIRMADA
```

- Fase 1 (votação): `PREPARE TRANSACTION` obriga o shard a gravar tudo em disco e a garantir que consegue fazer commit mais tarde, mesmo depois de reiniciar. Mantém os locks.
- Se algum participante vota NÃO (saldo insuficiente, conta bloqueada, timeout, falha) → `ROLLBACK PREPARED` nos que já tinham preparado → `ABORTADA` (teste `test_participant_failure_rolls_back_the_prepared_one`: `PREPARADO_EU, VOTO_NAO_AM, ROLLBACK_EU, ABORTADA`).
- Fase 2: só depois de a decisão estar **durável** no log é que se envia `COMMIT PREPARED`.

## 4. Como o 2PC garante ACID numa transação distribuída

| Propriedade | Mecanismo no projeto |
|---|---|
| **Atomicidade** | Uma decisão única e durável (`DECISAO_COMMIT` no pg-core) para os dois shards. Antes dela → todos fazem rollback (presumed abort); depois dela → todos fazem commit, nem que seja pela recuperação. Nunca um sem o outro. |
| **Consistência** | Restrições na própria BD (`CHECK balance >= 0`, IBAN da região certa), validações no participante (saldo, estado, limite diário) **antes** de votar SIM; `/admin/consistency` verifica o invariante global (cada CONFIRMADA = 1 débito + 1 crédito). |
| **Isolamento** | `SELECT … FOR UPDATE` bloqueia cada conta desde a fase 1 até ao `COMMIT PREPARED`: nenhuma outra transação vê ou altera o saldo intermédio. Ordem global de locks (EU → AM, depois por IBAN) evita deadlocks distribuídos; `lock_timeout` como rede de segurança. |
| **Durabilidade** | PREPARE escrito no WAL (sobrevive a reinício e é replicado); estado do coordenador gravado (commit) no pg-core antes de cada ação. |

## 5. Falhas testadas (evidências)

| Falha | Momento | Resultado | Evidência |
|---|---|---|---|
| Participante vota NÃO | fase 1 | rollback dos preparados, ABORTADA | `test_participant_failure_…`, `test_insufficient_funds_…` |
| Coordenador morre | depois do PREPARE, antes da decisão | após 30 s: `RECUPERACAO_ROLLBACK_*`, ABORTADA | `test_crash_before_decision_is_presumed_abort` |
| Coordenador morre | depois da decisão | Docker reinicia; `RECUPERACAO_COMMIT_*`, CONFIRMADA | cenário 10 |
| Shard cai | entre PREPARE e COMMIT | `COMMIT_PENDENTE_AM`; recovery com backoff; commit quando volta | cenário 09 |
| 50 pedidos concorrentes | — | 0 deadlocks, dinheiro conservado ao cêntimo | cenário 11 |

## 6. Porquê *presumed abort*

Se o coordenador não encontra decisão no log, assume abort. É seguro porque o commit só acontece **depois** de a decisão estar gravada: se não há registo, nenhum participante pode ter feito commit. Como bónus, o abort não precisa de ser gravado antes de avisar os participantes.

## 7. Limitação clássica do 2PC: bloqueio

Se o coordenador cair depois do PREPARE, os participantes não podem decidir sozinhos (não sabem o que o outro votou) e mantêm os locks até o coordenador voltar. No cenário 10 isso durou cerca de 1 s (reinício automático). Alternativas: 3PC (não bloqueia, mas não tolera partições), coordenador replicado com consenso (Paxos/Raft), ou **Saga** (sequência de transações locais com compensações; sem locks longos, mas só com consistência eventual e sem isolamento entre passos).
