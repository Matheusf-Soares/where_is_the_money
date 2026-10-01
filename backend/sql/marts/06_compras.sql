-- Parcelas só aparecem como compra após associação explicitamente confirmada.
CREATE OR REPLACE VIEW compras AS
WITH membros AS (
    SELECT t.*, row_number() OVER (PARTITION BY t.id_compra ORDER BY t.data, t.id_transacao) AS posicao
    FROM transacoes_analiticas t
    WHERE t.id_compra IS NOT NULL AND t.valor_assinado < 0
      AND NOT t.e_pagamento_de_fatura AND NOT t.e_transferencia_propria AND NOT t.e_aplicacao
      AND NOT t.e_saldo_anterior AND NOT t.e_pendente_substituida
), ids AS (
    SELECT id_compra, to_json(list(id_transacao ORDER BY id_transacao))::VARCHAR AS ids_transacoes
    FROM membros GROUP BY id_compra
), base AS (
SELECT 'transacao:' || id_transacao AS id_compra, coalesce(data_compra_fonte, data) AS data, instituicao, id_conta, conta,
    tipo_de_conta, estabelecimento, descricao, categoria, macro_categoria,
    id_categoria_propria, origem_da_categoria, essencialidade, comportamento,
    valor_brl, moeda, valor_original, to_json(list_value(id_transacao))::VARCHAR AS ids_transacoes,
    false AS e_parcelado, origem_data_gasto
FROM gastos_analiticos WHERE NOT e_parcelado AND coalesce(data_compra_fonte, data) <= current_date
UNION ALL
SELECT c.id, c.data_compra, t.instituicao, t.id_conta, t.conta,
    t.tipo_de_conta, t.estabelecimento, c.descricao, t.categoria, t.macro_categoria,
    t.id_categoria_propria, t.origem_da_categoria, t.essencialidade, t.comportamento,
    c.valor_total_brl, 'BRL', NULL::DECIMAL(18,2), ids.ids_transacoes, true, 'compra_confirmada'
FROM usr_compras c JOIN membros t ON t.id_compra = c.id AND t.posicao = 1
JOIN ids ON ids.id_compra = c.id
WHERE c.data_compra <= current_date
), datas AS (
    SELECT *, data AS data_gasto, extract(isodow FROM data)::INTEGER AS dia_semana_iso,
        CASE extract(isodow FROM data)
            WHEN 1 THEN 'segunda-feira' WHEN 2 THEN 'terça-feira' WHEN 3 THEN 'quarta-feira'
            WHEN 4 THEN 'quinta-feira' WHEN 5 THEN 'sexta-feira' WHEN 6 THEN 'sábado'
            WHEN 7 THEN 'domingo' END AS dia_semana
    FROM base
)
SELECT *, dia_semana_iso AS dia_semana_gasto_iso, dia_semana AS dia_semana_gasto FROM datas;
