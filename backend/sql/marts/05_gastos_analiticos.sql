CREATE OR REPLACE VIEW gastos_analiticos AS
SELECT * FROM transacoes_analiticas WHERE e_gasto;
