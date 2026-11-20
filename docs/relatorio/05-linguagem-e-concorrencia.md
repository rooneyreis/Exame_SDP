# Linguagem e concorrência (rascunho)

## Python 3.12 + asyncio (serviços principais)

- O sistema é **I/O-bound**: quase todo o tempo é espera por rede (HTTP entre serviços, PostgreSQL, NFS). Com asyncio, um único processo atende muitos pedidos: enquanto um espera pela BD, o *event loop* avança os outros (coroutines com `async`/`await`).
- Exemplos no código:
  - `asyncio.gather` no cenário 11 (`scripts/demo/concurrency.py`): 50 transferências em paralelo a partir de um único processo cliente, 2,6 s no total.
  - `asyncio.Semaphore` no coordenador (`tx_slots`): limita a 20 as transações simultâneas (contrapressão sobre as ligações aos shards).
  - `asyncio.Lock` na auditoria (`common/audit.py`): uma escrita de cada vez por processo, para a cadeia de hashes não se misturar.
  - `asyncio.create_task`: tarefas de fundo (refresh do JWKS na api, recovery loop no coordenador).
  - `asyncio.wait_for`: timeout de 10 s por participante na fase 1 do 2PC.
  - `contextvars` (`common/logging.py`): `request_id`/`tx_id` por tarefa, sem misturar pedidos concorrentes nos logs.
- **GIL**: o interpretador CPython executa bytecode Python numa thread de cada vez. Num sistema I/O-bound isso quase não pesa, porque o GIL é libertado durante as esperas de I/O. Onde há trabalho de CPU real (hash Argon2 no login), usa-se `asyncio.to_thread` para não bloquear o event loop (o Argon2 está em C e liberta o GIL).
- Escalar além de um núcleo: mais processos/instâncias (é o que fazemos com api-1 e api-2 atrás do Nginx).
- Sockets: Uvicorn (servidor ASGI sobre `uvloop`/asyncio), `httpx.AsyncClient`, psycopg 3 em modo assíncrono, tudo não bloqueante.

## Comparação

| Linguagem | Modelo | Nota |
|---|---|---|
| Python | coroutines (asyncio), threads com GIL, processos | simples e explícito; ideal para I/O; CPU pesado → processos |
| Java 21 (módulo legado) | threads do SO + **virtual threads** (Project Loom) | `HttpsServer` com executor; threads reais em paralelo, sem GIL |
| Go | goroutines + canais | concorrência leve nativa, M:N scheduler |
| C# | async/await sobre Task + thread pool | modelo semelhante ao asyncio, mas multi-core |

## Java 21 no módulo legado

- `HttpsServer.setExecutor(Executors.newVirtualThreadPerTaskExecutor())` (`legacy-bank/src/LegacyBank.java`): cada pedido corre numa **virtual thread**. O código é bloqueante e simples (ler o corpo, validar, escrever no ficheiro), mas milhares de threads virtuais custam pouca memória e a JVM multiplexa-as sobre poucas threads do SO.
- Secção crítica explícita: `Ledger.append` é `synchronized`, para que dois pedidos simultâneos não intercalem bytes no mesmo registo de largura fixa. É o equivalente Java do `asyncio.Lock` da auditoria em Python.
- Contraste: em Python a concorrência é cooperativa (um `await` cede o controlo); em Java as threads são preemptivas e correm em paralelo em vários núcleos, por isso o estado partilhado precisa de sincronização.
