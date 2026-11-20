-- Demo accounts of one shard. Run with: psql -v region=EU -v currency=EUR -v uuid_prefix=11111111
-- Opening balances are 10 000 / 5 000 / 2 500 units of the shard currency, times "scale"
-- (default 1; the MZN shard uses 50 so its clients hold comparable amounts).
-- The user_ids are fixed so the auth seed (Phase 2) can create the matching users.
-- Idempotent: existing accounts are left untouched.
INSERT INTO accounts (iban, user_id, currency, balance) VALUES
  ('GS-' || :'region' || '-00000001', (:'uuid_prefix' || '-0000-4000-8000-000000000001')::uuid, :'currency', 10000.00 * :scale),
  ('GS-' || :'region' || '-00000002', (:'uuid_prefix' || '-0000-4000-8000-000000000002')::uuid, :'currency',  5000.00 * :scale),
  ('GS-' || :'region' || '-00000003', (:'uuid_prefix' || '-0000-4000-8000-000000000003')::uuid, :'currency',  2500.00 * :scale)
ON CONFLICT (iban) DO NOTHING;

-- Daily limit in the shard currency follows the same scale (50 000 x scale), also for
-- accounts opened later through KYC (column default). Volumes created before this rule
-- had 50 000 on every shard: only those untouched defaults are raised.
ALTER TABLE accounts ALTER COLUMN daily_limit SET DEFAULT 50000.00 * :scale;
UPDATE accounts SET daily_limit = 50000.00 * :scale WHERE daily_limit = 50000.00 AND :scale <> 1;

-- New accounts (created after KYC) continue from 00000004.
SELECT setval('iban_seq', GREATEST(3, (SELECT last_value FROM iban_seq)));

SELECT iban, currency, balance FROM accounts ORDER BY iban;
