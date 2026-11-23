-- Transferência PENDENTE: um nó estava em baixo; o coordenador conclui-a quando o nó voltar.
SET ROLE coord_svc;
ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_state_check;
ALTER TABLE transactions ADD CONSTRAINT transactions_state_check
  CHECK (state IN ('INICIADA','PREPARANDO','DECISAO_COMMIT','CONFIRMADA','ABORTADA','PENDENTE'));
