-- Encerramento de contas: a conta passa a ENCERRADA e nunca é apagada.
ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_status_check;
ALTER TABLE accounts ADD CONSTRAINT accounts_status_check CHECK (status IN ('ATIVA','BLOQUEADA','ENCERRADA'));
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;
