# Capturas de ecrã

O enunciado pede capturas de ecrã das transações e do comportamento durante as falhas. Os `.log` da pasta acima têm o texto completo de cada cenário. Aqui ficam as imagens para o PDF.

Sugestão (uma captura por momento-chave, com o terminal em ecrã inteiro):

| Ficheiro | Cenário | Momento a capturar |
|---|---|---|
| `01-shards.png` | 01 | consulta direta aos dois Postgres: cada conta só no shard da sua região |
| `03-timeline-2pc.png` | 03 | linha temporal `INICIADA … CONFIRMADA` + liquidação no legado |
| `04-idempotencia.png` | 04 | 3 envios, mesmo `tx_id`, 1 débito |
| `05-adulteracao.png` | 05 | ataques recusados + linha adulterada detetada |
| `06-queda-api.png` | 06 | `docker stop api-1` e todas as respostas `X-Served-By: api-2` |
| `07-queda-auth.png` | 07 | auth parado, token continua válido, login novo falha |
| `08-failover.png` | 08 | `docker stop pg-europa`, a cópia em pg-america:5433 a assumir (`./scripts/topologia.sh`) e transferências a funcionar |
| `09-queda-2pc.png` | 09 | `COMMIT_PENDENTE_AM` → `RECUPERACAO_COMMIT_AM` |
| `10-crash.png` | 10 | `RestartCount 0 → 1` e `RECUPERACAO_COMMIT_*` |
| `11-concorrencia.png` | 11 | 50 transferências, conservação do dinheiro ✔ |
| `13-particao.png` | 13 | as duas variantes (commit concluído / abortada sem débito) |

Correr com pausas para ter tempo de capturar: `PAUSE=1 ./scripts/demo/run-all.sh`.
