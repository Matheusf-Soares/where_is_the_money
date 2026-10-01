-- O mês da fatura é o do vencimento, independente da data das compras.
-- Não subtrair payments: a fonte registra eventos do ciclo seguinte.
CREATE OR REPLACE VIEW faturas AS
WITH contas AS (
    SELECT *, row_number() OVER (PARTITION BY id ORDER BY data_posicao DESC) AS posicao
    FROM raw_contas
)
SELECT f.id AS id_fatura, f.id_conta, f.instituicao,
    c.nome AS conta, c.numero AS numero_cartao,
    f.vencimento, strftime(f.vencimento, '%Y-%m') AS mes_referencia,
    f.fechamento, f.valor_total, upper(f.moeda) AS moeda,
    CASE WHEN upper(f.moeda) = 'BRL' THEN f.valor_total END::DECIMAL(18,2) AS valor_brl,
    f.pagamento_minimo, f.permite_parcelamento, f.pagamentos_json, f.encargos_json,
    f.atualizado_em, l.coletado_em
FROM raw_faturas f
LEFT JOIN contas c ON c.id = f.id_conta AND c.posicao = 1
LEFT JOIN log_faturas l ON l.id_conta = f.id_conta;
