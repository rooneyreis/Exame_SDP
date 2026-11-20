# Limitações conhecidas e trabalho futuro (rascunho)

| Limitação | Impacto | Em produção |
|---|---|---|
| **Coordenador 2PC único** | Enquanto está em baixo, as transferências distribuídas ficam bloqueadas e os shards mantêm os locks das transações preparadas. **Nunca há inconsistência** (log durável + recuperação, cenário 10). | Coordenador replicado com consenso (Raft/Paxos), ou padrão Saga. |
| **2PC bloqueante** | Entre o PREPARE e a decisão, as contas envolvidas ficam bloqueadas (no cenário 09, durante a pausa de 20 s). | Saga com compensações (consistência eventual, sem locks longos). |
| **pg-core sem réplica** | É o log do coordenador e a BD de utilizadores: se cair, não há logins novos nem transferências (as leituras das contas continuam). | Réplica streaming como nos shards, ou Patroni. |
| **Failover manual** (`failover.sh`) | Exige um operador. Se os dois nós de uma região caírem e o antigo primário arrancar primeiro, as escritas feitas no promovido perdem-se. | Patroni + etcd (eleição por consenso, *fencing*). |
| **Replicação assíncrona** | Numa queda abrupta do primário, as últimas transações podem não ter chegado à réplica (incluindo PREPAREs). | `synchronous_standby_names` (custo: latência de escrita). |
| **NFS com um único servidor** | Ponto único de falha para auditoria e relatórios (as operações de negócio continuam: as falhas de escrita no NFS são registadas, não bloqueiam). | GlusterFS/CephFS replicado. |
| `Graceless = true` no NFS-Ganesha | Após um reinício do servidor NFS, os clientes não têm período para recuperar locks. | Manter o *grace period* (90 s). |
| **Simulação numa só máquina** | Todos os "nós" correm na mesma VM do Docker Desktop: a latência entre regiões é ~0 e todos os mounts NFS passam pelo mesmo kernel cliente. | Nós em máquinas/regiões diferentes. |
| **Liquidação REJEITADA** não é compensada | O dinheiro já se moveu entre shards; a rejeição fica registada. | Saga de estorno automática. |
| **Access token stateless** | O logout revoga o refresh token, mas o access token vale até expirar (máx. 15 min). | Lista de `jti` revogados ou tokens mais curtos. |
| **Auditoria** | Quem tem escrita no NFS pode reescrever o ficheiro inteiro com hashes novos. | Ancoragem externa do último hash, armazenamento WORM. |
| **KYC simulado** | O operador aprova manualmente, sem verificação documental. | Integração com fornecedor de KYC. |
| **Taxas de câmbio fixas** | Tabela `fx_rates` estática. | Fonte de cotações em tempo real, com validade da cotação. |
| **Segredos em ficheiros** | Chaves e senhas em ficheiros montados (`infra/keys`, `.env`). | Vault/KMS, rotação de chaves (o `kid` do JWT já permite rotação). |
