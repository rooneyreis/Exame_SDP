# Segurança (rascunho — notas das Fases 1 e 2; completar nas Fases 4–6)

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
