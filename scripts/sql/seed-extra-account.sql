-- Conta adicional de um cliente noutra região (contas múltiplas).
-- psql -v user_id=... -v currency=USD -v region=AM -v balance=1500
-- Idempotente: só cria se o cliente ainda não tiver uma conta ativa nesta moeda neste shard.
INSERT INTO accounts (iban, user_id, currency, balance, daily_limit)
SELECT 'GS-' || :'region' || '-' || lpad(nextval('iban_seq')::text, 8, '0'), :'user_id'::uuid, :'currency', :balance,
       CASE WHEN :'currency' = 'MZN' THEN 2500000 ELSE 50000 END
WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE user_id = :'user_id'::uuid AND currency = :'currency' AND status <> 'ENCERRADA');
SELECT iban, currency, balance FROM accounts WHERE user_id = :'user_id'::uuid;
