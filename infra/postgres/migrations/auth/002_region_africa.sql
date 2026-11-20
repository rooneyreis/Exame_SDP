-- Região África (AF, moeda MZN): as constraints de região passam a aceitar AF.
-- Corre sobre volumes existentes (os dados não são tocados); instalações novas já
-- recebem estas constraints em infra/postgres/init/core/01-init.sh.
SET ROLE auth_svc;

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_region_check;
ALTER TABLE users ADD CONSTRAINT users_region_check CHECK (region IN ('EU','AM','AF'));

ALTER TABLE beneficiaries DROP CONSTRAINT IF EXISTS beneficiaries_iban_check;
ALTER TABLE beneficiaries ADD CONSTRAINT beneficiaries_iban_check CHECK (iban ~ '^GS-(EU|AM|AF)-[0-9]{8}$');
