# Relatório técnico: rascunhos

Rascunhos em Markdown das secções do relatório (PDF) pedido no enunciado. Cada afirmação aponta para o ficheiro do código ou para a evidência (`docs/evidencias/`) que a demonstra.

| Ficheiro | Conteúdo | Parte do enunciado |
|---|---|---|
| [00-requisitos-do-docente.md](00-requisitos-do-docente.md) | cada ponto do que o docente espera ver → código → evidência | todas |
| [01-arquitetura.md](01-arquitetura.md) | diagrama, nós, IPs, DNS, fluxo de uma transferência | Parte 1 + entregáveis |
| [02-centralizado-vs-distribuido.md](02-centralizado-vs-distribuido.md) | latência, ponto único de falha, escalabilidade; CAP; transparências | Parte 1 |
| [03-so-distribuido-e-dfs.md](03-so-distribuido-e-dfs.md) | NFS v4: transparência de localização, locks, cache, relatório partilhado | Parte 1 |
| [04-bdd-e-2pc-acid.md](04-bdd-e-2pc-acid.md) | fragmentação, replicação, 2PC passo a passo, ACID, presumed abort, 2PC vs. Saga | Parte 2 |
| [05-linguagem-e-concorrencia.md](05-linguagem-e-concorrencia.md) | justificação do Python (asyncio, GIL) e do Java 21 (virtual threads) | Parte 2 |
| [06-servicos-web-e-interoperabilidade.md](06-servicos-web-e-interoperabilidade.md) | REST/JSON, REST vs. gRPC, interoperabilidade Python ↔ Java em XML | Parte 3 |
| [07-omg-oma.md](07-omg-oma.md) | análise comparativa OMG/OMA (CORBA, ORB, OTS) vs. microsserviços | Parte 3 |
| [08-seguranca.md](08-seguranca.md) | TLS, JWT, AES-GCM, Argon2, Ed25519, auditoria; defesa em profundidade | Parte 4 |
| [09-tolerancia-a-falhas.md](09-tolerancia-a-falhas.md) | cada cenário de falha com o comportamento e a evidência | entregáveis |
| [10-limitacoes.md](10-limitacoes.md) | limitações e o que se faria em produção | entregáveis |

PDF final: [`relatorio.pdf`](relatorio.pdf), gerado por `python scripts/build-report.py` (precisa de `pip install markdown` e de Chrome ou Edge). O script junta os capítulos por ordem, desenha os diagramas Mermaid e imprime em A4. Para incluir as capturas de `docs/evidencias/capturas/`, referencie-as nos capítulos e volte a gerar o PDF.
