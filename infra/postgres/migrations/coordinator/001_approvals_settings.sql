-- Transferências registadas por operadores (com aprovação), limites configuráveis e
-- rastreabilidade de quem iniciou/aprovou cada transação.
SET ROLE coord_svc;

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS initiated_by   UUID;   -- quem submeteu a ordem
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS initiated_role TEXT;   -- cliente | operador
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS approved_by    UUID;   -- administrador que aprovou (se aplicável)
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS request_id     UUID;   -- pedido de transferência de origem

-- Parâmetros institucionais alterados pelo administrador.
CREATE TABLE IF NOT EXISTS settings (
  key         TEXT PRIMARY KEY,
  value       NUMERIC(18,2) NOT NULL CHECK (value > 0),
  description TEXT NOT NULL,
  updated_by  UUID,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO settings (key, value, description) VALUES
  ('max_transfer_amount', 10000, 'Montante máximo por transferência (aplicado pela API e pelo coordenador)'),
  ('approval_threshold', 5000, 'Transferências registadas por operadores a partir deste montante exigem aprovação de um administrador')
ON CONFLICT (key) DO NOTHING;

-- Pedidos de transferência registados por operadores (maker-checker).
CREATE TABLE IF NOT EXISTS transfer_requests (
  id               UUID PRIMARY KEY,
  created_by       UUID NOT NULL,
  created_by_role  TEXT NOT NULL,
  owner_id         UUID NOT NULL,          -- titular da conta de origem
  from_iban        TEXT NOT NULL,
  to_iban          TEXT NOT NULL,
  amount           NUMERIC(18,2) NOT NULL CHECK (amount > 0),
  currency         TEXT NOT NULL,
  beneficiary_name TEXT,
  description      TEXT,
  status           TEXT NOT NULL CHECK (status IN ('PENDENTE_APROVACAO','REJEITADA','EM_EXECUCAO','EXECUTADA','FALHADA')),
  requires_approval BOOLEAN NOT NULL,
  tx_id            UUID,
  decided_by       UUID,
  decided_at       TIMESTAMPTZ,
  decision_reason  TEXT,
  client_ip        TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (from_iban <> to_iban)
);
CREATE INDEX IF NOT EXISTS transfer_requests_status_idx ON transfer_requests (status, created_at DESC);

-- A API regista e decide pedidos e lê/altera os limites. Não há DELETE para ninguém:
-- os registos financeiros não podem ser apagados pela aplicação.
GRANT SELECT, INSERT, UPDATE ON transfer_requests TO api_svc;
GRANT SELECT, UPDATE ON settings TO api_svc;
