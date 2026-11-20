# Segurança (rascunho)

## Quatro mecanismos diferentes (não confundir)

| Mecanismo | Onde | Protege contra |
|---|---|---|
| Hash lento (Argon2id) | senhas (`services/auth/auth_service/main.py`) | fuga da BD → senhas não recuperáveis (ataques de dicionário caros: 64 MiB por tentativa) |
| Cifragem simétrica autenticada (AES-256-GCM) | `document_id`, `birth_date` (`common/crypto.py`) | quem lê a BD/backups sem a chave; adulteração (tag GCM); trocar valores entre utilizadores (AAD = `user_id`) |
| Cifragem de canal (TLS 1.2/1.3) | cliente → nginx → serviços → Postgres, replicação | escuta e alteração na rede; `verify-full` também protege contra servidores falsos (verifica a CA e o nome) |
| Assinatura digital (RS256, Ed25519) | JWT; mensagens api → coordinator → legacy (Fase 4/5) | falsificação: só quem tem a chave privada assina, qualquer um verifica |

## Autenticação distribuída (JWT RS256)

- Assimétrico **de propósito**: com HS256 (chave partilhada) todos os nós que validam poderiam também **emitir** tokens. Com RS256 só o `auth` tem a chave privada, e os outros nós só têm a pública (JWKS).
- Validação local em cada nó (sem perguntar ao `auth`): baixa latência e o `auth` não é ponto único de falha para pedidos já autenticados (cenário 07).
- Claims verificados: `exp`, `iss`, `aud`, `kid`; algoritmo fixo RS256 (ataque `alg: none` testado em `tests/unit/test_jwt_auth.py`).
- Refresh tokens: opacos, guardados como SHA-256, com rotação e deteção de reutilização.

## Evidências já recolhidas

- `tests/integration/test_phase1_postgres.py`: ligação sem TLS recusada; certificado de outro nó recusado (`does not match host name`); replicação sobre TLS 1.3.
- `tests/integration/test_phase2_auth.py`: bloqueio após 5 falhas, rotação de refresh, token adulterado recusado, documento cifrado na BD (o texto em claro não aparece nos bytes guardados).
- Na Fase 2, o Python 3.14 recusou a CA local por não ter a extensão `keyUsage` (verificação X.509 estrita). A CA foi corrigida (RFC 5280: `basicConstraints=CA:TRUE`, `keyUsage=keyCertSign,cRLSign`).

## Integridade de mensagens (Fases 4–5)

- api → coordinator: JSON canónico + `X-Payload-SHA256` + `X-Signature` (Ed25519) + `X-Signer`. O coordenador só confia nas chaves públicas de api-1 e api-2. Janela temporal de 5 min contra *replay*; `tx_id` tem de corresponder à `Idempotency-Key`.
- Cenário 05: cinco ataques a partir de dentro da rede (montante alterado, SHA-256 recalculado, sem assinatura, assinante desconhecido, replay de 10 min) → todos recusados e registados como `ADULTERACAO_DETETADA` na auditoria.
- coordinator ↔ legacy: o mesmo esquema dentro do XML, nos dois sentidos (ordem e ack assinados).
- Porquê Ed25519: assinaturas curtas (64 bytes), rápidas, sem parâmetros perigosos de escolher (ao contrário de ECDSA com nonce aleatório), suportadas pela `cryptography` e pelo Java 15+.
- Porquê assinatura e não só hash: um SHA-256 sozinho deteta alterações acidentais, mas um atacante pode recalculá-lo (`sha256_recalculado` no cenário 05). Só a assinatura prova quem enviou.

## Defesa em profundidade (resumo)

| Camada | Controlo |
|---|---|
| Rede | só a porta 443 exposta; rede interna isolada; TLS 1.2+ em tudo (cenário 12) |
| Transporte | TLS com CA própria e verificação do nome (SAN) em todos os saltos, incluindo a replicação |
| Identidade | JWT RS256 de 15 min, refresh rotativo com deteção de roubo, bloqueio após 5 falhas |
| Autorização | roles por endpoint; clientes só veem as suas contas (404, não 403) |
| Mensagens | assinaturas Ed25519 + SHA-256, anti-replay, idempotência |
| Dados em repouso | AES-256-GCM nos dados pessoais; Argon2id nas senhas; privilégio mínimo nas roles da BD |
| Entrada | Pydantic (montantes decimais, limites), parser XML sem DTD (XXE), corpo máximo 64 KiB |
| Auditoria | log encadeado por hash no NFS, verificável (`/admin/audit`) |
