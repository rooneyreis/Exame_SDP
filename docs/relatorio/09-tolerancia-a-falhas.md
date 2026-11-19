# Tolerância a falhas (rascunho — completar com os cenários 08–10 e 13)

| Cenário | O que cai | O que o sistema faz | Evidência |
|---|---|---|---|
| 06 | `api-1` | Nginx deteta a falha (timeout de ligação de 2 s), repete o pedido na `api-2` e deixa de tentar a `api-1` durante 10 s. Nenhum pedido do cliente falha. | `docs/evidencias/06-queda-api.log`: linha do nginx com `"upstream":"172.28.0.11:8000, 172.28.0.12:8000","upstream_status":"504, 200"` |
| 07 | `auth` | Tokens já emitidos continuam válidos nas duas api (chave pública em cache). Logins novos falham (5xx). Tokens forjados continuam rejeitados. | `docs/evidencias/07-queda-auth.log` |
| Fase 1 | primário de um shard | `failover.sh` promove a réplica; conninfo multi-host encontra o novo primário; o antigo primário volta como réplica. | `tests/integration/test_phase1_zz_failover.py` |

## Notas para a explicação teórica

- **Redundância ativa (api)**: duas instâncias *stateless* (sem estado em memória entre pedidos: o estado está na BD e no token). Por isso qualquer instância serve qualquer pedido, e o balanceador pode trocar livremente.
- **Deteção de falha passiva** no Nginx (`max_fails`/`fail_timeout`): não há sondas ativas, a falha é detetada no próprio pedido.
- **Idempotência vs. retry**: o Nginx só repete POSTs que nunca chegaram ao backend. As transferências terão `Idempotency-Key` (Fase 4), o que tornaria seguro repeti-las mesmo nesse caso.
- **Autenticação sem ponto único de falha** para pedidos autenticados: o `auth` só é necessário para emitir tokens, não para os validar.
