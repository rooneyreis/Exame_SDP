-- Várias contas por cliente (em regiões e moedas diferentes), pedidos de abertura e de
-- encerramento, e limite diário por CLIENTE em EUR.
SET ROLE coord_svc;

-- Pedidos dos clientes (ou do balcão), decididos por um operador. Nunca apagados.
CREATE TABLE IF NOT EXISTS account_requests (
  id               UUID PRIMARY KEY,
  user_id          UUID NOT NULL,                 -- titular
  kind             TEXT NOT NULL CHECK (kind IN ('ABERTURA','ENCERRAMENTO')),
  region           TEXT NOT NULL CHECK (region IN ('EU','AM','AF')),
  currency         TEXT NOT NULL CHECK (currency IN ('EUR','USD','MZN')),
  iban             TEXT,                          -- conta a encerrar, ou a conta aberta
  status           TEXT NOT NULL CHECK (status IN ('PENDENTE','APROVADO','REJEITADO')),
  created_by       UUID NOT NULL,
  created_by_role  TEXT NOT NULL,
  decided_by       UUID,
  decided_at       TIMESTAMPTZ,
  decision_reason  TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS account_requests_status_idx ON account_requests (status, created_at DESC);
CREATE INDEX IF NOT EXISTS account_requests_user_idx ON account_requests (user_id, created_at DESC);
-- No máximo um pedido pendente por (cliente, região, moeda) e por conta a encerrar.
CREATE UNIQUE INDEX IF NOT EXISTS account_requests_one_open_pending
  ON account_requests (user_id, region, currency) WHERE status = 'PENDENTE' AND kind = 'ABERTURA';
CREATE UNIQUE INDEX IF NOT EXISTS account_requests_one_close_pending
  ON account_requests (iban) WHERE status = 'PENDENTE' AND kind = 'ENCERRAMENTO';

-- Limite diário por cliente: cada transferência guarda o seu valor em EUR (à taxa do
-- momento) e se é entre contas do mesmo titular (essas não contam para o limite).
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS amount_eur   NUMERIC(18,2);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS own_transfer BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS transactions_user_day_idx ON transactions (user_id, created_at);

-- Novos parâmetros institucionais. O máximo por transferência passa a ser em EUR.
INSERT INTO settings (key, value, description) VALUES
  ('max_accounts_per_client', 5, 'Número máximo de contas ativas por cliente'),
  ('daily_limit_eur', 50000, 'Limite diário por cliente (soma dos envios de todas as contas, em EUR)')
ON CONFLICT (key) DO NOTHING;
UPDATE settings SET description = 'Montante máximo por transferência, em EUR (convertido para a moeda da conta de origem)'
 WHERE key = 'max_transfer_amount';

GRANT SELECT, INSERT, UPDATE ON account_requests TO api_svc;
