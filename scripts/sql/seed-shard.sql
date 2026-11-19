-- Demo accounts of one shard. Run with: psql -v region=EU -v currency=EUR -v uuid_prefix=11111111
-- The user_ids are fixed so the auth seed (Phase 2) can create the matching users.
-- Idempotent: existing accounts are left untouched.
INSERT INTO accounts (iban, user_id, currency, balance) VALUES
  ('GS-' || :'region' || '-00000001', (:'uuid_prefix' || '-0000-4000-8000-000000000001')::uuid, :'currency', 10000.00),
  ('GS-' || :'region' || '-00000002', (:'uuid_prefix' || '-0000-4000-8000-000000000002')::uuid, :'currency',  5000.00),
  ('GS-' || :'region' || '-00000003', (:'uuid_prefix' || '-0000-4000-8000-000000000003')::uuid, :'currency',  2500.00)
ON CONFLICT (iban) DO NOTHING;

-- New accounts (created after KYC) continue from 00000004.
SELECT setval('iban_seq', GREATEST(3, (SELECT last_value FROM iban_seq)));

SELECT iban, currency, balance FROM accounts ORDER BY iban;
