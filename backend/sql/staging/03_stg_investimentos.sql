-- stg_investimentos: retratos diários de posição.
--
-- Armadilha 3: isto nunca é somado com transação. A tabela de origem é separada
-- por construção e esta view não toca em raw_transacoes.

CREATE OR REPLACE VIEW stg_investimentos AS
SELECT
    id                      AS id_investimento,
    data_posicao,
    data_referencia,
    id_item,
    instituicao,
    nome,
    tipo,
    subtipo,
    emissor,
    moeda,
    data_aplicacao,
    data_vencimento,
    taxa,
    tipo_taxa,
    quantidade,
    valor_aplicado,
    saldo,
    -- A API manda amountProfit, mas ela nem sempre vem. Recalcular a partir do
    -- que existe evita um NULL bobo no meio do patrimônio.
    coalesce(rendimento, saldo - valor_aplicado)  AS rendimento,
    situacao,
    data_posicao = max(data_posicao) OVER ()      AS e_retrato_atual
FROM raw_investimentos;
