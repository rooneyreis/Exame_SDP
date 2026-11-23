-- Custódia de créditos para regiões totalmente indisponíveis (ver bank/002_custodia.sql).
SET ROLE coord_svc;

-- Onde cada perna da transferência foi executada. DIRETA: nas regiões das contas.
-- CUSTODIA: pelo menos uma perna foi executada noutro shard, em custódia da conta.
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS routing TEXT NOT NULL DEFAULT 'DIRETA'
  CHECK (routing IN ('DIRETA','CUSTODIA'));
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS debit_region  TEXT;   -- NULL = from_region
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS credit_region TEXT;   -- NULL = to_region

-- Diretório de contas (cópia de iban -> titular, região, moeda, estado). Permite validar uma
-- conta cuja região está em baixo. Atualizado pela api ao criar contas e sincronizado pelo
-- coordenador a partir dos shards.
CREATE TABLE IF NOT EXISTS account_directory (
  iban       TEXT PRIMARY KEY,
  user_id    UUID NOT NULL,
  region     TEXT NOT NULL,
  currency   TEXT NOT NULL,
  status     TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS account_directory_user_idx ON account_directory (user_id);

-- Log durável dos reencaminhamentos (2PC entre o shard que guardou o valor e a região de destino).
CREATE TABLE IF NOT EXISTS custody_forwards (
  forward_id    UUID PRIMARY KEY,
  holder_region TEXT NOT NULL,
  target_iban   TEXT NOT NULL,
  target_region TEXT NOT NULL,
  amount        NUMERIC(18,2),                       -- saldo restante creditado no destino
  currency      TEXT,
  movements     INT,                                 -- movimentos do histórico reencaminhados
  state         TEXT NOT NULL CHECK (state IN ('PREPARANDO','DECISAO_COMMIT','CONCLUIDO','ABORTADO')),
  reason        TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS custody_forwards_pending_idx ON custody_forwards (state)
  WHERE state IN ('PREPARANDO','DECISAO_COMMIT');

GRANT SELECT, INSERT, UPDATE ON account_directory TO api_svc;
GRANT SELECT ON custody_forwards TO api_svc;
