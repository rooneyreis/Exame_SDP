#!/usr/bin/env bash
# Shard primary (pg-europa / pg-america / pg-africa): database "bank" with accounts and movements.
# Runs once, on the first start of the PRIMARY. Replicas receive everything
# (roles included) through pg_basebackup + streaming replication.
# SHARD_REGION (EU|AM|AF) makes the fragmentation rule explicit in the schema.
set -euo pipefail
echo "[init:shard-$SHARD_REGION] a criar roles e base de dados bank"
# Daily limit per account, in the shard currency: 50 000 EUR/USD; the MZN shard uses the
# equivalent order of magnitude (x50), like its opening balances.
DAILY_LIMIT=50000
[[ "$SHARD_REGION" == "AF" ]] && DAILY_LIMIT=2500000

psql -v ON_ERROR_STOP=1 -U postgres -d postgres <<SQL
CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '${REPLICATION_PASSWORD}';
CREATE ROLE coord_svc LOGIN PASSWORD '${COORD_DB_PASSWORD}';
CREATE ROLE api_svc   LOGIN PASSWORD '${API_DB_PASSWORD}';
CREATE DATABASE bank;
REVOKE ALL ON DATABASE bank FROM PUBLIC;
GRANT CONNECT ON DATABASE bank TO coord_svc, api_svc;
SQL

psql -v ON_ERROR_STOP=1 -U postgres -d bank <<SQL
-- Horizontal fragmentation: this shard only stores IBANs of its own region.
CREATE TABLE accounts (
  iban        TEXT PRIMARY KEY CHECK (iban ~ '^GS-${SHARD_REGION}-[0-9]{8}\$'),
  user_id     UUID NOT NULL,
  currency    TEXT NOT NULL CHECK (currency IN ('EUR','USD','MZN')),
  balance     NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
  status      TEXT NOT NULL DEFAULT 'ATIVA' CHECK (status IN ('ATIVA','BLOQUEADA','ENCERRADA')),
  closed_at   TIMESTAMPTZ,
  daily_limit NUMERIC(18,2) NOT NULL DEFAULT ${DAILY_LIMIT},
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX accounts_user_idx ON accounts (user_id);

CREATE TABLE movements (
  id            BIGSERIAL PRIMARY KEY,
  iban          TEXT NOT NULL REFERENCES accounts(iban),
  tx_id         UUID NOT NULL,
  type          TEXT NOT NULL CHECK (type IN ('DEBITO','CREDITO')),
  amount        NUMERIC(18,2) NOT NULL CHECK (amount > 0),
  currency      TEXT NOT NULL,
  balance_after NUMERIC(18,2) NOT NULL,
  -- Transfers are logged by the coordinator; deposits/withdrawals are local operations
  -- of the shard. /admin/consistency uses this to tell them apart.
  origin        TEXT NOT NULL DEFAULT 'TRANSFERENCIA'
                CHECK (origin IN ('TRANSFERENCIA','DEPOSITO','LEVANTAMENTO')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tx_id, iban, type)          -- idempotency at shard level
);
CREATE INDEX movements_iban_idx ON movements (iban, created_at);

-- Sequential part of new IBANs (GS-<region>-00000001).
CREATE SEQUENCE iban_seq;

GRANT SELECT, INSERT, UPDATE ON accounts, movements TO coord_svc, api_svc;
GRANT USAGE ON SEQUENCE iban_seq, movements_id_seq TO coord_svc, api_svc;
SQL

echo "[init:shard-$SHARD_REGION] concluído"
