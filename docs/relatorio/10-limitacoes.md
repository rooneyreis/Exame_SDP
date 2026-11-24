# Limitações conhecidas e trabalho futuro (rascunho)

| Limitação | Impacto | Em produção |
|---|---|---|
| **Coordenador 2PC único** | Enquanto está em baixo, as transferências distribuídas ficam bloqueadas e os shards mantêm os locks das transações preparadas. **Nunca há inconsistência** (log durável + recuperação, cenário 10). | Coordenador replicado com consenso (Raft/Paxos), ou padrão Saga. |
| **2PC bloqueante** | Entre o PREPARE e a decisão, as contas envolvidas ficam bloqueadas (no cenário 09, durante a pausa de 20 s). | Saga com compensações (consistência eventual, sem locks longos). |
| **Supervisor próprio em vez de consenso** | A decisão de assumir usa testemunhas (os outros nós). Uma partição que separe só o dono da sua cópia, com ambos a verem as testemunhas, pode deixar os dois a aceitar escritas durante segundos; quando se encontram, o de timeline mais antiga perde-as. | Patroni + etcd/Consul (eleição por consenso, *leader lock*). |
| **Replicação assíncrona com a cópia em baixo** | Enquanto a cópia de uma base está em baixo, o dono continua sozinho (assíncrono). Se o dono cair nessa janela, essas escritas só voltam com ele (a cópia desatualizada nunca é promovida). | Duas cópias por base (quórum `ANY 1`). |
| **Uma cópia por base** | Se um nó e o nó que guarda a sua cópia caírem juntos, essa região fica sem cópia viva; só a custódia de créditos funciona. | Duas ou mais cópias, noutras regiões. |
| **NFS com um único servidor** | Ponto único de falha para auditoria e relatórios (as operações de negócio continuam: as falhas de escrita no NFS são registadas, não bloqueiam). | GlusterFS/CephFS replicado. |
| `Graceless = true` no NFS-Ganesha | Após um reinício do servidor NFS, os clientes não têm período para recuperar locks. | Manter o *grace period* (90 s). |
| **Simulação numa só máquina** | Todos os "nós" correm na mesma VM do Docker Desktop: a latência entre regiões é ~0 e todos os mounts NFS passam pelo mesmo kernel cliente. | Nós em máquinas/regiões diferentes. |
| **Liquidação REJEITADA** não é compensada | O dinheiro já se moveu entre shards; a rejeição fica registada. | Saga de estorno automática. |
| **Access token stateless** | O logout revoga o refresh token, mas o access token vale até expirar (máx. 15 min). | Lista de `jti` revogados ou tokens mais curtos. |
| **Auditoria** | Quem tem escrita no NFS pode reescrever o ficheiro inteiro com hashes novos. | Ancoragem externa do último hash, armazenamento WORM. |
| **KYC simulado** | O operador aprova manualmente, sem verificação documental. | Integração com fornecedor de KYC. |
| **Taxas de câmbio fixas** | Tabela `fx_rates` estática. | Fonte de cotações em tempo real, com validade da cotação. |
| **Segredos em ficheiros** | Chaves e senhas em ficheiros montados (`infra/keys`, `.env`). | Vault/KMS, rotação de chaves (o `kid` do JWT já permite rotação). |
