-- Gestão de utilizadores pelo administrador + beneficiários guardados no servidor.
SET ROLE auth_svc;

-- Novo estado: conta desativada pelo administrador (diferente de bloqueada temporariamente).
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_status_check;
ALTER TABLE users ADD CONSTRAINT users_status_check
  CHECK (status IN ('PENDENTE_VERIFICACAO', 'ATIVA', 'BLOQUEADA', 'DESATIVADA'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_by UUID;

-- Beneficiários de cada cliente (antes ficavam só no browser).
CREATE TABLE IF NOT EXISTS beneficiaries (
  id         UUID PRIMARY KEY,
  owner_id   UUID NOT NULL REFERENCES users(id),
  name       TEXT NOT NULL CHECK (length(name) BETWEEN 2 AND 120),
  iban       TEXT NOT NULL CHECK (iban ~ '^GS-(EU|AM)-[0-9]{8}$'),
  nickname   TEXT,
  favorite   BOOLEAN NOT NULL DEFAULT false,
  created_by UUID NOT NULL,              -- o próprio cliente, ou o operador que o registou
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (owner_id, iban)
);
CREATE INDEX IF NOT EXISTS beneficiaries_owner_idx ON beneficiaries (owner_id);
