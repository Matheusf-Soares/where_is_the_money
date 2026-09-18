-- O staging preserva a resolução TOML e todas as bandeiras financeiras.
-- As personalizações são resolvidas depois, sem modificar raw nem exclusões.
CREATE OR REPLACE VIEW transacoes_analiticas AS
WITH contas AS (
    SELECT *, row_number() OVER (PARTITION BY id_conta ORDER BY data_posicao DESC) AS posicao
    FROM stg_contas
), base AS (
    SELECT t.*, r.descricao_original, r.id_categoria AS id_categoria_pluggy,
        c.nome AS conta, c.tipo AS tipo_de_conta,
        coalesce(nullif(json_extract_string(try_cast(r.payload_json AS JSON), '$.paymentData.paymentMethod'), ''),
                 nullif(json_extract_string(try_cast(r.payload_json AS JSON), '$.paymentMethod'), ''),
                 CASE WHEN c.tipo = 'CREDIT' THEN 'Crédito' ELSE 'Não informada' END) AS forma_pagamento,
        CASE WHEN upper(t.moeda) = 'BRL' THEN abs(t.valor)
             WHEN upper(c.moeda) = 'BRL' THEN abs(try_cast(json_extract_string(
                 try_cast(r.payload_json AS JSON), '$.amountInAccountCurrency') AS DECIMAL(18,2)))
        END::DECIMAL(18,2) AS valor_brl,
        try_cast(json_extract_string(try_cast(r.payload_json AS JSON), '$.creditCardMetadata.purchaseDate') AS DATE) AS data_compra_fonte,
        try_cast(json_extract_string(try_cast(r.payload_json AS JSON), '$.creditCardMetadata.totalAmount') AS DECIMAL(18,2)) AS valor_total_fonte,
        json_extract_string(try_cast(r.payload_json AS JSON), '$.creditCardMetadata.billId') AS id_fatura
    FROM stg_transacoes t
    JOIN raw_transacoes r ON r.id = t.id_transacao
    LEFT JOIN contas c ON c.id_conta = t.id_conta AND c.posicao = 1
), regras AS (
    SELECT b.id_transacao, r.id_categoria,
        row_number() OVER (PARTITION BY b.id_transacao ORDER BY r.prioridade) AS posicao
    FROM base b JOIN usr_regras r ON r.ativa
        AND lower(coalesce(b.instituicao, '')) LIKE lower(r.instituicao)
        AND (lower(b.descricao) LIKE lower(r.padrao)
          OR lower(coalesce(b.descricao_original, '')) LIKE lower(r.padrao)
          OR lower(coalesce(b.estabelecimento, '')) LIKE lower(r.padrao))
), aliases AS (
    SELECT b.id_transacao, a.estabelecimento,
        row_number() OVER (PARTITION BY b.id_transacao ORDER BY
            CASE WHEN a.instituicao = '%' THEN 1 ELSE 0 END, a.instituicao) AS posicao
    FROM base b JOIN usr_aliases a
        ON lower(b.descricao_original) = lower(a.descricao_original)
       AND (a.instituicao = '%' OR lower(b.instituicao) = lower(a.instituicao))
), resolucao AS (
    SELECT b.*, coalesce(m.id_categoria, r.id_categoria,
        CASE WHEN b.origem_da_categoria <> 'regra' THEN mapa.id_categoria END) AS id_categoria_propria,
        CASE WHEN m.id_categoria IS NOT NULL THEN 'manual'
             WHEN r.id_categoria IS NOT NULL THEN 'regra_ui'
             WHEN b.origem_da_categoria = 'regra' THEN 'regra_toml'
             WHEN mapa.id_categoria IS NOT NULL THEN 'mapa_ui'
             WHEN b.origem_da_categoria = 'mapa' THEN 'mapa_toml'
             ELSE b.origem_da_categoria END AS origem_resolvida,
        coalesce(a.estabelecimento, b.estabelecimento, b.descricao) AS estabelecimento_resolvido,
        coalesce(b.parcela_total > 1, false) AS e_parcelado,
        coalesce(b.valor_assinado < 0 AND NOT b.e_futura AND NOT b.e_pagamento_de_fatura
            AND NOT b.e_transferencia_propria AND NOT b.e_aplicacao, false) AS e_gasto
    FROM base b
    LEFT JOIN usr_classificacoes m ON m.id_transacao = b.id_transacao
    LEFT JOIN regras r ON r.id_transacao = b.id_transacao AND r.posicao = 1
    LEFT JOIN usr_mapas mapa ON mapa.id_categoria_pluggy = b.id_categoria_pluggy
    LEFT JOIN aliases a ON a.id_transacao = b.id_transacao AND a.posicao = 1
)
SELECT b.id_transacao, b.id_conta, b.instituicao, b.conta, b.tipo_de_conta,
    b.cartao_final, b.data, b.descricao, b.descricao_original,
    b.estabelecimento_resolvido AS estabelecimento, b.moeda,
    abs(b.valor)::DECIMAL(18,2) AS valor_original, b.valor_assinado,
    b.valor_brl, (CASE WHEN b.valor_assinado < 0 THEN -b.valor_brl
                     WHEN b.valor_assinado >= 0 THEN b.valor_brl END)::DECIMAL(18,2) AS valor_assinado_brl,
    b.situacao, b.categoria_pluggy, b.id_categoria_pluggy, b.id_categoria_propria,
    coalesce(c.nome, b.categoria) AS categoria,
    coalesce(c.macro_categoria, b.grupo || ' (legado)') AS macro_categoria,
    b.origem_resolvida AS origem_da_categoria,
    coalesce(a.essencialidade, c.essencialidade, 'nao_definido') AS essencialidade,
    coalesce(a.comportamento, c.comportamento, 'nao_definido') AS comportamento,
    b.e_parcelado, b.parcela_numero, b.parcela_total, b.e_futura,
    b.e_pagamento_de_fatura, b.e_transferencia_propria, b.e_aplicacao, b.e_gasto,
    CASE WHEN b.e_gasto THEN NULL
         WHEN b.e_pagamento_de_fatura THEN 'pagamento_de_fatura'
         WHEN b.e_transferencia_propria THEN 'transferencia_propria'
         WHEN b.e_aplicacao THEN 'aplicacao'
         WHEN b.e_futura THEN 'futura'
         ELSE 'entrada_ou_sem_valor' END AS motivo_exclusao,
    b.data_compra_fonte, b.valor_total_fonte, b.id_fatura, cp.id_compra,
    b.e_parcelado AND cp.id_compra IS NULL AS compra_pendente,
    b.forma_pagamento,
    CASE WHEN a.id_transacao IS NOT NULL THEN 'manual' ELSE 'categoria' END AS origem_atributos,
    NOT b.e_parcelado AND EXISTS (SELECT 1 FROM usr_recorrencias r
        WHERE lower(trim(r.instituicao)) = lower(trim(b.instituicao))
          AND lower(trim(r.estabelecimento)) = lower(trim(b.estabelecimento_resolvido))
          AND r.estado = 'ativa') AS e_recorrente
FROM resolucao b
LEFT JOIN usr_categorias c ON c.id = b.id_categoria_propria
LEFT JOIN usr_atributos a ON a.id_transacao = b.id_transacao
LEFT JOIN usr_compra_transacoes cp ON cp.id_transacao = b.id_transacao;
