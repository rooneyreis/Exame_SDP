# Tolerância a falhas (rascunho)

| Cenário | O que cai | O que o sistema faz | Evidência |
|---|---|---|---|
| 06 | `api-1` | Nginx deteta a falha (timeout de ligação de 2 s), repete o pedido na `api-2` e deixa de tentar a `api-1` durante 10 s. Nenhum pedido do cliente falha. | `docs/evidencias/06-queda-api.log`: linha do nginx com `"upstream":"172.28.0.11:8000, 172.28.0.12:8000","upstream_status":"504, 200"` |
| 07 | `auth` | Tokens já emitidos continuam válidos nas duas api (chave pública em cache). Logins novos falham (5xx). Tokens forjados continuam rejeitados. | `docs/evidencias/07-queda-auth.log` |
| 08 | nó `pg-europa` | A cópia da Europa em `pg-america:5433` assume o papel sozinha em ~6–10 s; transferências LOCAL e 2PC, depósitos e levantamentos continuam sem mudar configuração; as leituras nunca param. Quando `pg-europa` volta, sincroniza-se a partir da cópia e retoma o papel (switchover sem perdas). | `docs/evidencias/08-queda-shard-failover.log`, `test_phase1_zz_failover.py` |
| 09 | `pg-america` entre o PREPARE e o COMMIT | Decisão COMMIT já durável; Europa faz commit; a cópia da América (`pg-africa:5433`) assume e já tem a transação preparada (replicação síncrona); o recovery faz `COMMIT PREPARED` nela, sem esperar pelo `pg-america`. Sem dinheiro perdido. | `docs/evidencias/09-queda-durante-2pc.log` |
| 10 | processo do coordenador, depois da decisão | Docker reinicia-o (`restart: unless-stopped`); recovery lê `DECISAO_COMMIT` e conclui em ~1 s; o cliente repete com a mesma `Idempotency-Key` sem duplicar. | `docs/evidencias/10-crash-coordenador.log` |
| (teste) | processo do coordenador, antes da decisão | Presumed abort: após 30 s, `ROLLBACK PREPARED` nos dois shards. | `test_crash_before_decision_is_presumed_abort` |
| 13A | **rede** do `pg-america` depois do PREPARE | `pg-america` não vê nenhum outro nó: fica só de leitura (nunca dois primários). A cópia em `pg-africa` assume; `COMMIT_PENDENTE_AM` é concluído nela pelo recovery. Quando a rede volta, `pg-america` sincroniza-se e retoma o papel. | `docs/evidencias/13-particao-rede.log` |
| 13B | **rede** do `pg-america` antes do PREPARE | A América não responde (não é um voto NÃO) → `ROLLBACK_EU`, `PENDENTE`; o saldo de origem não muda. Quando a cópia assume, o recovery retoma a transferência (`RETOMADA`) e fica `CONFIRMADA`, com um único débito. | idem |
| 17 | **região inteira**: `pg-africa` **e** `pg-europa` (que guarda a sua cópia) | Transferências e depósitos para contas AF são confirmados e ficam em custódia noutro shard ativo (`routing=CUSTODIA`, `DESVIO_CUSTODIA`); a titular usa o valor retido até ao montante guardado; quando África volta, um 2PC próprio reencaminha o saldo restante e reproduz o histórico no extrato (`REENCAMINHADA_PARA_AF`). Primário em baixo com réplica ativa **não** ativa a custódia (espera pelo failover). | `docs/evidencias/17-custodia-regiao-em-baixo.log`, `test_phase11_custody.py` |
| (teste) | `legacy-bank` | Transferências não são afetadas; liquidação fica `PENDENTE` e é reenviada quando o legado volta. | `test_settlement_waits_while_legacy_is_down` |

## Notas para a explicação teórica

- **Redundância ativa (api)**: duas instâncias *stateless* (sem estado em memória entre pedidos: o estado está na BD e no token). Por isso qualquer instância serve qualquer pedido, e o balanceador pode trocar livremente.
- **Deteção de falha passiva** no Nginx (`max_fails`/`fail_timeout`): não há sondas ativas, a falha é detetada no próprio pedido.
- **Idempotência vs. retry**: o Nginx só repete POSTs que nunca chegaram ao backend. As transferências terão `Idempotency-Key` (Fase 4), o que tornaria seguro repeti-las mesmo nesse caso.
- **Autenticação sem ponto único de falha** para pedidos autenticados: o `auth` só é necessário para emitir tokens, não para os validar.

- **Falha de nó vs. falha de rede**: `docker stop` (09) mata o processo. `docker network disconnect` (13) deixa o processo vivo mas inacessível, que é o caso mais difícil, porque o outro lado não sabe se o nó morreu ou se está só lento. Os timeouts (connect 3 s, `tcp_user_timeout` 8 s, 10 s por participante) transformam o "não sei" numa falha detetável.
- **Consistência acima de disponibilidade (CAP)**: perante a partição, o sistema prefere abortar ou esperar a completar metade da transferência.
