# Sistema centralizado vs. distribuído (rascunho)

## O cenário

A Global Scale Corporation tem clientes na Europa e na América e processa transações financeiras internacionais com requisitos de alta disponibilidade. A pergunta é: porque não um único servidor com uma única base de dados?

## Limitações de um sistema centralizado neste cenário

| Limitação | Num sistema centralizado | No sistema distribuído implementado |
|---|---|---|
| **Latência** | Um cliente em Maputo ou em Nova Iorque fala sempre com o mesmo datacenter. Cada pedido atravessa continentes (ida e volta transatlântica ≈ 80–150 ms, várias vezes por operação). | Dados fragmentados por região: as contas de cada cliente vivem no shard da sua região. Em produção, cada shard ficaria fisicamente perto dos seus clientes. Só as transferências entre regiões pagam o custo inter-regional (2PC). |
| **Ponto único de falha** | Se o servidor ou a BD cair, o banco inteiro pára. | Várias redundâncias, demonstradas: 2 instâncias de api (cenário 06), réplica por shard com failover (08), validação de tokens sem o auth (07), recuperação do coordenador (10), shard isolado sem perda de dinheiro (09, 13). Uma falha numa região não pára a outra: transferências EU→EU continuam com a América em baixo. |
| **Escalabilidade** | Só vertical (máquina maior), com um limite físico e um custo crescente. Uma BD única é o gargalo de escrita. | Horizontal: mais instâncias de api atrás do nginx (sem estado); mais shards para mais regiões ou mais clientes; leituras podem ir às réplicas. |
| **Manutenção** | Atualizar = parar tudo. | Atualizações rolantes (parar api-1, atualizar, voltar; o nginx manda tudo para a api-2). |
| **Soberania dos dados** | Todos os dados numa jurisdição. | Dados de clientes europeus num nó europeu (RGPD), americanos num nó americano. |
| **Desempenho sob carga** | Toda a concorrência numa única fila de locks. | Locks repartidos por shard: transferências em regiões diferentes não competem. |

## O preço do distribuído (e como foi tratado)

| Problema novo | Solução no projeto |
|---|---|
| Atomicidade entre BDs diferentes | Two-Phase Commit com log durável e recuperação (`04-bdd-e-2pc-acid.md`) |
| Falhas parciais (um nó cai, os outros não) | presumed abort, retries com backoff, idempotência |
| Falhas de rede (partições) | timeouts, keepalives TCP, decisão durável, cenário 13 |
| Segurança de mensagens na rede | TLS em todos os canais, assinaturas Ed25519, JWT verificável localmente |
| Ficheiros partilhados entre nós | NFS v4 com locks no servidor |
| Observabilidade | logs JSON com `request_id`/`tx_id`, auditoria encadeada, `/admin/status`, `/admin/consistency` |
| Complexidade operacional | Docker Compose, scripts de failover, testes automáticos |

## Teorema CAP aplicado

Perante uma partição de rede, o sistema escolhe **consistência** (CP) nas transferências: no cenário 13, uma transferência para a América isolada é abortada (variante B) ou fica à espera da rede (variante A), mas nunca fica meio feita. A disponibilidade é preservada onde não compromete a consistência: as operações locais da região que continua acessível funcionam normalmente.

## Transparências (Tanenbaum)

| Transparência | Onde |
|---|---|
| Localização | o cliente usa `https://localhost`, não sabe que há 2 apis nem 5 BDs; `/audit` parece local mas está no nó NFS |
| Replicação | o cliente não sabe que existe réplica |
| Falha | failover do nginx entre apis; conninfo multi-host nos shards |
| Concorrência | 50 transferências simultâneas com resultado igual ao sequencial (cenário 11) |
| Migração / relocalização | após failover o primário muda de IP sem mudar a configuração dos serviços |
