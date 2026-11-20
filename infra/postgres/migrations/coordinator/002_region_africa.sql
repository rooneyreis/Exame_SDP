-- Região África (AF): o log do 2PC passa a aceitar transações de e para AF.
SET ROLE coord_svc;

ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_from_region_check;
ALTER TABLE transactions ADD CONSTRAINT transactions_from_region_check CHECK (from_region IN ('EU','AM','AF'));
ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_to_region_check;
ALTER TABLE transactions ADD CONSTRAINT transactions_to_region_check CHECK (to_region IN ('EU','AM','AF'));
