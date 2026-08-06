-- recorrencias: assinaturas ativas e quanto custam por ano.
--
-- Heurística, não verdade absoluta: um estabelecimento que cobra em vários
-- meses distintos, com valor estável, é tratado como assinatura.
--
-- Os dois limiares vêm de cfg_geral (`recorrencia_meses_minimos` e
-- `recorrencia_variacao_maxima`), então calibrar a detecção é editar o
-- regras.toml e rodar `views` de novo — sem tocar neste arquivo.
--
-- Por que variação e não valor idêntico: assinatura em dólar oscila com o
-- câmbio, e plano de academia sobe uma vez por ano. Exigir igualdade exata
-- perderia justamente as que mais importam.

CREATE OR REPLACE VIEW recorrencias AS
WITH limites AS (
    SELECT
        CAST(max(CASE WHEN chave = 'recorrencia_meses_minimos'   THEN valor END) AS INTEGER) AS meses_minimos,
        CAST(max(CASE WHEN chave = 'recorrencia_variacao_maxima' THEN valor END) AS DOUBLE)  AS variacao_maxima
    FROM cfg_geral
),
-- Agrupa por mês antes de comparar: quem faz duas compras no mesmo mês no mesmo
-- lugar (mercado, por exemplo) não pode parecer que assinou alguma coisa.
por_mes AS (
    SELECT
        estabelecimento,
        instituicao,
        ano,
        mes,
        sum(valor) AS valor_no_mes
    FROM gastos
    GROUP BY estabelecimento, instituicao, ano, mes
),
resumo AS (
    SELECT
        estabelecimento,
        instituicao,
        count(*)             AS meses_observados,
        min(valor_no_mes)    AS valor_minimo,
        max(valor_no_mes)    AS valor_maximo,
        avg(valor_no_mes)    AS valor_medio,
        min(ano * 100 + mes) AS primeiro_mes,
        max(ano * 100 + mes) AS ultimo_mes
    FROM por_mes
    GROUP BY estabelecimento, instituicao
)
SELECT
    r.estabelecimento,
    r.instituicao,
    r.meses_observados,
    r.primeiro_mes,
    r.ultimo_mes,
    r.valor_medio,
    r.valor_minimo,
    r.valor_maximo,
    -- Amplitude relativa ao valor médio. Zero quando o valor nunca mudou.
    (r.valor_maximo - r.valor_minimo) / nullif(r.valor_medio, 0) AS variacao,
    r.valor_medio * 12                                           AS custo_anual_estimado
FROM resumo r
CROSS JOIN limites l
WHERE r.meses_observados >= l.meses_minimos
  AND (r.valor_maximo - r.valor_minimo) / nullif(r.valor_medio, 0) <= l.variacao_maxima
ORDER BY r.valor_medio DESC;
