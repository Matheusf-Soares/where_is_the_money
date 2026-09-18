CREATE OR REPLACE VIEW recorrencias_analiticas AS
WITH limites AS (
    SELECT cast(max(CASE WHEN chave = 'recorrencia_meses_minimos' THEN valor END) AS INTEGER) AS meses_minimos,
        cast(max(CASE WHEN chave = 'recorrencia_variacao_maxima' THEN valor END) AS DOUBLE) AS variacao_maxima
    FROM cfg_geral
), meses AS (
    SELECT lower(trim(estabelecimento)) AS chave_estabelecimento,
        lower(trim(instituicao)) AS chave_instituicao,
        min(estabelecimento) AS estabelecimento, min(instituicao) AS instituicao, id_conta,
        EXTRACT(YEAR FROM data) * 100 + EXTRACT(MONTH FROM data) AS mes,
        sum(valor_brl) AS valor
    FROM gastos_analiticos WHERE NOT e_parcelado AND valor_brl IS NOT NULL
    GROUP BY chave_estabelecimento, chave_instituicao, id_conta, mes
), resumo AS (
    SELECT chave_estabelecimento, chave_instituicao,
        min(estabelecimento) AS estabelecimento, min(instituicao) AS instituicao,
        id_conta, count(*) AS meses_observados,
        min(mes) AS primeiro_mes, max(mes) AS ultimo_mes,
        cast(avg(valor) AS DECIMAL(18,2)) AS valor_medio_brl,
        cast(avg(valor) * 12 AS DECIMAL(18,2)) AS custo_anual_estimado_brl,
        (max(valor) - min(valor)) / nullif(avg(valor), 0) AS variacao
    FROM meses GROUP BY chave_estabelecimento, chave_instituicao, id_conta
)
SELECT coalesce(r.estabelecimento, u.estabelecimento) AS estabelecimento,
    coalesce(r.instituicao, u.instituicao) AS instituicao, r.id_conta,
    coalesce(r.meses_observados, 0) AS meses_observados, r.primeiro_mes, r.ultimo_mes,
    r.valor_medio_brl, r.custo_anual_estimado_brl,
    coalesce(u.estado, 'sugestao') AS estado, r.variacao
FROM resumo r FULL OUTER JOIN usr_recorrencias u
    ON lower(trim(u.instituicao)) = r.chave_instituicao AND lower(trim(u.estabelecimento)) = r.chave_estabelecimento
CROSS JOIN limites l
WHERE u.estado IS NOT NULL OR (r.meses_observados >= l.meses_minimos AND r.variacao <= l.variacao_maxima);
