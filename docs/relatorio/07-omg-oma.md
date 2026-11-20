# OMG/OMA e os microsserviços atuais: análise comparativa (rascunho)

## 1. A Object Management Architecture (OMA)

A OMG (Object Management Group, 1989) definiu a OMA como arquitetura de referência para objetos distribuídos. Os componentes:

- **ORB (Object Request Broker)**: o "barramento" que entrega pedidos de um cliente a um objeto remoto, escondendo a localização, a linguagem e o SO do objeto. A especificação concreta é o **CORBA** (Common Object Request Broker Architecture).
- **Object Services (CORBAservices)**: serviços de infraestrutura genéricos: Naming, Event, Transaction (OTS), Security, Concurrency Control, Persistence, Lifecycle…
- **Common Facilities**: serviços de nível mais alto partilhados por aplicações (gestão de documentos, impressão…).
- **Domain Interfaces**: interfaces normalizadas por setor (finanças, saúde, telecomunicações).
- **Application Objects**: os objetos da própria aplicação.

Peças técnicas do CORBA: **IDL** (Interface Definition Language, contrato neutro em linguagem, compilado em *stubs* no cliente e *skeletons* no servidor), **IIOP** (protocolo de transporte entre ORBs sobre TCP), **IOR** (referência que identifica um objeto remoto), POA (adaptador de objetos no servidor).

## 2. Correspondências com o projeto

| Conceito OMA/CORBA | Equivalente no Global-Scale System | Ficheiro |
|---|---|---|
| ORB (encaminhar o pedido sem o cliente saber onde está o objeto) | Nginx (balanceamento, failover) + HTTP/TLS entre serviços | `infra/nginx/nginx.conf` |
| IDL + stubs/skeletons | OpenAPI gerada pelo FastAPI (`/openapi.json`) + modelos Pydantic; o contrato XML do legado | `services/*/schemas.py`, `coordinator_service/settlement.py` |
| IIOP | HTTP/1.1 sobre TLS, corpo JSON ou XML | — |
| IOR (referência de objeto) | URI de recurso (`/accounts/GS-EU-00000001`) | — |
| Naming Service | DNS interno `*.global.local` | `docker-compose.yml` (aliases) |
| **Transaction Service (OTS)**: 2PC entre recursos transacionais | **coordinator**: 2PC sobre `PREPARE TRANSACTION` do PostgreSQL | `coordinator_service/main.py` |
| Security Service (autenticação, credenciais propagadas) | JWT RS256 propagado em cada chamada, TLS mútuo de confiança via CA | `common/jwt_auth.py` |
| Event Service / Notification | eventos `tx_events` e auditoria no NFS (sem broker) | `common/audit.py` |
| Concurrency Control Service | locks de linha do PostgreSQL, `fcntl.lockf` no NFS | `common/reports.py` |
| Interoperabilidade entre ORBs de fabricantes diferentes (GIOP/IIOP) | Python ↔ Java pelo contrato XML assinado | `legacy-bank/` |

O OTS do CORBA (e o modelo X/Open XA de que deriva) é praticamente o que o nosso coordenador implementa: um gestor de transações que fala com vários gestores de recursos e decide commit/abort em duas fases. O PostgreSQL faz o papel de *resource manager* XA.

## 3. O que os microsserviços e o REST/gRPC herdaram

- **Contratos formais independentes da linguagem**: IDL → OpenAPI (REST) e `.proto` (gRPC). O gRPC é, na prática, o herdeiro mais direto do CORBA: IDL compilada para stubs em várias linguagens, chamadas tipadas, binário.
- **Transparência de localização**: o cliente não sabe que instância responde (ORB → balanceador/service discovery).
- **Serviços transversais separados da lógica**: CORBAservices → serviços de identidade (o nosso `auth`), DNS/service discovery, gateways, *service mesh*.
- **Interoperabilidade entre tecnologias** como objetivo de primeira classe.

## 4. O que foi rejeitado (reflexão crítica)

| CORBA | Microsserviços/REST | Porquê a mudança |
|---|---|---|
| Objetos remotos **com estado** e referências a instâncias concretas | Recursos **sem estado**: cada pedido traz tudo (JWT) | Escala e falha: no cenário 06 qualquer api serve qualquer pedido. Com objetos com estado, a queda de um servidor invalidava as referências que os clientes tinham. |
| Chamada remota a parecer local (transparência total) | Chamadas de rede explícitas, com timeouts, retries e idempotência | As "falácias da computação distribuída": a rede falha e tem latência. Esconder isso levou a sistemas frágeis. O nosso código trata cada falha explicitamente (`Idempotency-Key`, `wait_for`, backoff). |
| Acoplamento forte (stubs gerados, versões sincronizadas) | Acoplamento fraco, evolução tolerante (campos novos ignorados) | Equipas e deploys independentes. |
| IIOP: portas dinâmicas, difícil de passar firewalls e proxies | HTTP(S) na porta 443, que passa por qualquer proxy | Na Internet, só a porta 443 do nginx está exposta. |
| Especificação enorme, ORBs de fabricantes pouco compatíveis na prática | Padrões web simples (HTTP, JSON, TLS, JWT), ferramentas universais (`curl`) | Custo de adoção; a demo inteira usa `curl` e `jq`. |
| Transações distribuídas como serviço genérico (OTS) | Preferência por Saga e consistência eventual; 2PC só onde é indispensável | O 2PC bloqueia e acopla disponibilidade (secção 7 de `04-bdd-e-2pc-acid.md`). Aqui usámos 2PC porque o enunciado exige garantias ACID numa transferência financeira. |

## 5. Conclusão

Os microsserviços não inventaram a computação distribuída por serviços: reorganizaram as ideias da OMA (contrato, broker, serviços comuns, transações coordenadas) sobre a Web, trocando a ilusão de "objeto remoto como se fosse local" por recursos sem estado e falhas explícitas. O nosso projeto mostra as duas faces: a arquitetura é de microsserviços REST, mas o coração (o coordenador 2PC) é conceptualmente um Transaction Service da OMA.

## Referências

- OMG, *Common Object Request Broker Architecture (CORBA) Specification*, v3.3; *Object Transaction Service Specification*.
- Tanenbaum & van Steen, *Distributed Systems*, cap. 8 (tolerância a falhas: commit distribuído) e cap. 10 (sistemas distribuídos baseados em objetos).
- Coulouris, Dollimore, Kindberg, Blair, *Distributed Systems: Concepts and Design*, cap. 8 (CORBA) e cap. 17 (transações distribuídas).
- Fielding, *Architectural Styles and the Design of Network-based Software Architectures* (REST), 2000.
- Deutsch, *The Eight Fallacies of Distributed Computing*.
