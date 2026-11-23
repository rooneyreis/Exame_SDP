-- Custódia: quando uma região está TOTALMENTE em baixo (primário e réplica), os créditos
-- destinados às suas contas ficam guardados aqui, noutro shard ativo, em nome da conta de
-- destino. O titular pode usar esse valor (transferir, levantar) enquanto a região está em
-- baixo. Quando a região volta, o coordenador reencaminha o saldo restante e o histórico.

CREATE TABLE IF NOT EXISTS custody_accounts (
  target_iban   TEXT PRIMARY KEY CHECK (target_iban ~ '^GS-[A-Z]{2}-[0-9]{8}$'),
  target_region TEXT NOT NULL,                       -- região a que a conta pertence
  user_id       UUID NOT NULL,                       -- titular da conta de destino
  currency      TEXT NOT NULL CHECK (currency IN ('EUR','USD','MZN')),   -- moeda da conta de destino
  balance       NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (balance >= 0),   -- valor retido utilizável
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS custody_movements (
  id            BIGSERIAL PRIMARY KEY,
  target_iban   TEXT NOT NULL REFERENCES custody_accounts(target_iban),
  tx_id         UUID NOT NULL,
  type          TEXT NOT NULL CHECK (type IN ('DEBITO','CREDITO')),
  amount        NUMERIC(18,2) NOT NULL CHECK (amount > 0),
  currency      TEXT NOT NULL,
  balance_after NUMERIC(18,2) NOT NULL,              -- saldo retido depois do movimento
  origin        TEXT NOT NULL CHECK (origin IN ('TRANSFERENCIA','DEPOSITO','LEVANTAMENTO','REENCAMINHAMENTO')),
  counterparty  TEXT,                                -- de onde veio (crédito) / para onde foi (débito)
  forwarded_by  UUID,                                -- reencaminhamento que o levou para a região de destino
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tx_id, target_iban, type)
);
CREATE INDEX IF NOT EXISTS custody_movements_pending_idx
  ON custody_movements (target_iban, id) WHERE forwarded_by IS NULL;

-- Movimentos reencaminhados: no extrato da conta de destino ficam com o nó onde aconteceram.
ALTER TABLE movements ADD COLUMN IF NOT EXISTS via_region TEXT;

GRANT SELECT, INSERT, UPDATE ON custody_accounts, custody_movements TO coord_svc, api_svc;
GRANT USAGE ON SEQUENCE custody_movements_id_seq TO coord_svc, api_svc;
