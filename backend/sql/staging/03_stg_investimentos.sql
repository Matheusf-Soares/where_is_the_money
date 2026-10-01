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
    -- Valor aplicado é só o `amountOriginal` do payload. Linhas antigas do raw
    -- guardaram `amount` (o valor atual) neste campo; ler do payload corrige
    -- sem reingestão e sem tocar no raw.
    try_cast(json_extract_string(try_cast(payload_json AS JSON), '$.amountOriginal') AS DECIMAL(18,2))
                                                    AS valor_aplicado,
    saldo,
    -- Rendimento informado pela fonte vence. Sem ele, só há conta a fazer
    -- quando existe valor aplicado de verdade; do contrário fica NULL, porque
    -- "não informado" não é zero.
    coalesce(
        rendimento,
        saldo - try_cast(json_extract_string(try_cast(payload_json AS JSON), '$.amountOriginal') AS DECIMAL(18,2))
    )                                               AS rendimento,
    situacao,
    data_posicao = max(data_posicao) OVER ()      AS e_retrato_atual
FROM raw_investimentos;
