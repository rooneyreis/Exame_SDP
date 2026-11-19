#!/usr/bin/env bash
# pg-core: databases "auth" (users) and "coordinator" (2PC log, FX rates).
# Runs once, on the first start (official image: /docker-entrypoint-initdb.d).
set -euo pipefail
echo "[init:pg-core] a criar roles e bases de dados auth + coordinator"

psql -v ON_ERROR_STOP=1 -U postgres -d postgres <<SQL
CREATE ROLE auth_svc  LOGIN PASSWORD '${AUTH_DB_PASSWORD}';
CREATE ROLE coord_svc LOGIN PASSWORD '${COORD_DB_PASSWORD}';
CREATE ROLE api_svc   LOGIN PASSWORD '${API_DB_PASSWORD}';
CREATE DATABASE auth        OWNER auth_svc;
CREATE DATABASE coordinator OWNER coord_svc;
REVOKE ALL ON DATABASE auth, coordinator FROM PUBLIC;
GRANT CONNECT ON DATABASE auth TO auth_svc;
GRANT CONNECT ON DATABASE coordinator TO coord_svc, api_svc;
SQL

# ---------- auth ----------
psql -v ON_ERROR_STOP=1 -U postgres -d auth <<'SQL'
SET ROLE auth_svc;

CREATE TABLE users (
  id              UUID PRIMARY KEY,
  full_name       TEXT NOT NULL,
  email           TEXT NOT NULL UNIQUE,
  phone           TEXT NOT NULL UNIQUE,
  password_hash   TEXT NOT NULL,                       -- Argon2id
  region          TEXT NOT NULL CHECK (region IN ('EU','AM')),
  document_id_enc BYTEA,                               -- AES-256-GCM: nonce || ciphertext
  birth_date_enc  BYTEA,                               -- AES-256-GCM: nonce || ciphertext
  role            TEXT NOT NULL CHECK (role IN ('cliente','operador','auditor','admin')),
  status          TEXT NOT NULL CHECK (status IN ('PENDENTE_VERIFICACAO','ATIVA','BLOQUEADA')),
  failed_attempts INT NOT NULL DEFAULT 0,
  locked_until    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE refresh_tokens (
  id         UUID PRIMARY KEY,
  user_id    UUID NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL UNIQUE,                     -- SHA-256 of the token, never the token
  expires_at TIMESTAMPTZ NOT NULL,
  revoked    BOOL NOT NULL DEFAULT false
);
SQL

# ---------- coordinator ----------
psql -v ON_ERROR_STOP=1 -U postgres -d coordinator <<'SQL'
SET ROLE coord_svc;

-- Durable log of the 2PC coordinator: one row per transfer.
CREATE TABLE transactions (
  tx_id             UUID PRIMARY KEY,
  idempotency_key   TEXT NOT NULL UNIQUE,
  user_id           UUID NOT NULL,
  from_iban         TEXT NOT NULL,
  to_iban           TEXT NOT NULL,
  from_region       TEXT NOT NULL CHECK (from_region IN ('EU','AM')),
  to_region         TEXT NOT NULL CHECK (to_region IN ('EU','AM')),
  amount            NUMERIC(18,2) NOT NULL CHECK (amount > 0),
  from_currency     TEXT NOT NULL,
  to_currency       TEXT NOT NULL,
  fx_rate           NUMERIC(18,8) NOT NULL,
  converted_amount  NUMERIC(18,2) NOT NULL,
  kind              TEXT NOT NULL CHECK (kind IN ('LOCAL','DISTRIBUIDA')),
  state             TEXT NOT NULL CHECK (state IN ('INICIADA','PREPARANDO','DECISAO_COMMIT','CONFIRMADA','ABORTADA')),
  failure_reason    TEXT,
  request_signature TEXT,
  request_sha256    TEXT,
  settlement_status TEXT NOT NULL DEFAULT 'N/A'
                    CHECK (settlement_status IN ('N/A','PENDENTE','ACEITE','REJEITADA')),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- The recovery loop looks for unfinished transactions.
CREATE INDEX transactions_pending_idx ON transactions (state)
  WHERE state IN ('INICIADA','PREPARANDO','DECISAO_COMMIT');

-- Timeline of each transaction (used by the demo and the report).
CREATE TABLE tx_events (
  id     BIGSERIAL PRIMARY KEY,
  tx_id  UUID NOT NULL REFERENCES transactions(tx_id),
  event  TEXT NOT NULL,
  detail JSONB,
  at     TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX tx_events_tx_idx ON tx_events (tx_id, id);

CREATE TABLE fx_rates (
  base  TEXT NOT NULL,
  quote TEXT NOT NULL,
  rate  NUMERIC(18,8) NOT NULL CHECK (rate > 0),
  PRIMARY KEY (base, quote)
);

-- The api reads transactions (GET /transfers, /admin/consistency) and FX rates.
GRANT SELECT ON transactions, tx_events, fx_rates TO api_svc;
SQL

echo "[init:pg-core] concluído"
