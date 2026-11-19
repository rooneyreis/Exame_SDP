-- FX rates (EUR, USD, MZN). Idempotent: can be re-run.
INSERT INTO fx_rates (base, quote, rate) VALUES
  ('EUR', 'USD', 1.08000000),
  ('USD', 'EUR', 0.92592593),
  ('EUR', 'MZN', 70.50000000),
  ('MZN', 'EUR', 0.01418440),
  ('USD', 'MZN', 63.90000000),
  ('MZN', 'USD', 0.01564945)
ON CONFLICT (base, quote) DO UPDATE SET rate = EXCLUDED.rate;
