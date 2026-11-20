# Serviços Web e Interoperabilidade (rascunho)

## REST/JSON (Fases 2–3)

- Recursos identificados por URI (`/accounts/{iban}`, `/accounts/{iban}/movements`), métodos HTTP com semântica (GET seguro e idempotente; POST para operações).
- Contrato publicado automaticamente em OpenAPI (`/docs`, `/openapi.json`), que é o equivalente moderno da IDL do CORBA (ver `07-omg-oma.md`).
- *Stateless*: cada pedido traz o JWT, e nenhuma instância guarda sessão. É o que permite o balanceamento e o failover do cenário 06.
- Códigos HTTP com significado: 401 (sem token/inválido), 403 (role sem permissão), 404 (conta inexistente ou de outro cliente, para não revelar que existe), 409 (saldo insuficiente, conflito de estado), 422 (validação), 423 (conta bloqueada), 503 (dependência em baixo).
- Valores monetários como **string decimal** (`"100.50"`), nunca float: evita erros de arredondamento binário.

## REST vs. gRPC (justificação da escolha)

- REST/JSON: legível (curl/jq na demo), suportado por qualquer linguagem, fácil de passar por proxies HTTP (Nginx). Custo: mais bytes, sem contrato tipado obrigatório (mitigado com OpenAPI + Pydantic).
- gRPC/Protobuf: contrato forte (`.proto`), binário, HTTP/2 com streaming. Seria preferível para chamadas internas de alto volume (ex.: api → coordinator).

## Interoperabilidade Python ↔ Java (Fase 5)

- Duas tecnologias diferentes (Python 3.12/FastAPI e Java 21 sem frameworks), dois formatos (JSON na API moderna, XML com o legado), um contrato comum:
  - estrutura XML fixa (`<SettlementOrder version="1.0">`, `<SettlementAck>`), com versão no elemento raiz para evolução futura;
  - montantes como texto decimal com 2 casas (`BigDecimal` em Java, `Decimal` em Python), nunca vírgula flutuante;
  - datas ISO-8601 UTC (`2026-11-19T23:54:50Z`);
  - chaves públicas em PEM padrão (SubjectPublicKeyInfo / PKCS#8), lidas por `cryptography` (Python) e por `X509EncodedKeySpec`/`PKCS8EncodedKeySpec` (Java).
- Integridade e autenticidade nos dois sentidos: o coordenador assina a ordem, o banco assina o ack. Cada lado só confia na chave pública do outro.
- Problema prático resolvido: assinar os **bytes do XML** falharia, porque cada biblioteca serializa de forma diferente (espaços, ordem de atributos, declaração). Solução: assinar uma string canónica dos campos. O padrão da indústria seria XML-DSig com canonicalização C14N.
- Segurança do parser: XML vindo da rede é perigoso (XXE: `<!ENTITY e SYSTEM "file:///etc/passwd">`). O DOM do Java está configurado para recusar qualquer DOCTYPE; teste `test_malformed_xml_and_xxe_are_rejected`.
- Herança de sistemas legados: registos de **largura fixa** (posição e comprimento de cada campo, montantes em cêntimos), como nos ficheiros COBOL/VSAM de mainframe. A integração moderna (HTTP/XML) é uma "fachada" à volta desse formato.
- Desacoplamento temporal: a liquidação é assíncrona e com novas tentativas, por isso uma indisponibilidade do legado não bloqueia as transferências (`test_settlement_waits_while_legacy_is_down`).

Evidências: `tests/integration/test_phase5_legacy.py`, `docs/evidencias/03-transferencia-2pc.log` (passo 5).
