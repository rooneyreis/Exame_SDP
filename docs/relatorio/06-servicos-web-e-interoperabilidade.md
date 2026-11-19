# Serviços Web e Interoperabilidade (rascunho — completar na Fase 5 com o legado Java/XML)

## REST/JSON (Fases 2–3)

- Recursos identificados por URI (`/accounts/{iban}`, `/accounts/{iban}/movements`), métodos HTTP com semântica (GET seguro e idempotente; POST para operações).
- Contrato publicado automaticamente em OpenAPI (`/docs`, `/openapi.json`), que é o equivalente moderno da IDL do CORBA (ver `07-omg-oma.md`).
- *Stateless*: cada pedido traz o JWT, e nenhuma instância guarda sessão. É o que permite o balanceamento e o failover do cenário 06.
- Códigos HTTP com significado: 401 (sem token/inválido), 403 (role sem permissão), 404 (conta inexistente ou de outro cliente, para não revelar que existe), 409 (saldo insuficiente, conflito de estado), 422 (validação), 423 (conta bloqueada), 503 (dependência em baixo).
- Valores monetários como **string decimal** (`"100.50"`), nunca float: evita erros de arredondamento binário.

## REST vs. gRPC (justificação da escolha)

- REST/JSON: legível (curl/jq na demo), suportado por qualquer linguagem, fácil de passar por proxies HTTP (Nginx). Custo: mais bytes, sem contrato tipado obrigatório (mitigado com OpenAPI + Pydantic).
- gRPC/Protobuf: contrato forte (`.proto`), binário, HTTP/2 com streaming. Seria preferível para chamadas internas de alto volume (ex.: api → coordinator).
