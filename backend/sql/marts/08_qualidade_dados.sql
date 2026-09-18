-- Timestamps raw indicam dados observados, não sucesso de sincronização.
CREATE OR REPLACE VIEW qualidade_dados AS
WITH instituicoes AS (
    SELECT instituicao FROM raw_contas UNION SELECT instituicao FROM raw_transacoes
    UNION SELECT instituicao FROM raw_investimentos UNION SELECT instituicao FROM log_sincronizacoes
), observacoes AS (
    SELECT instituicao, atualizado_em FROM raw_contas
    UNION ALL SELECT instituicao, atualizado_em FROM raw_transacoes
    UNION ALL SELECT instituicao, atualizado_em FROM raw_investimentos
), tempos AS (
    SELECT instituicao, max(atualizado_em) AS ultima_ingestao FROM observacoes GROUP BY instituicao
), contas AS (
    SELECT instituicao, count(DISTINCT id) AS contas, max(data_posicao) AS data_posicao
    FROM raw_contas GROUP BY instituicao
), posicoes AS (
    SELECT instituicao, max(data_posicao) AS data_posicao FROM (
        SELECT instituicao, data_posicao FROM raw_contas
        UNION ALL SELECT instituicao, data_posicao FROM raw_investimentos
    ) p GROUP BY instituicao
), transacoes AS (
    SELECT instituicao, min(data) FILTER (WHERE NOT e_futura) AS primeira_transacao,
        max(data) FILTER (WHERE NOT e_futura) AS ultima_transacao, count(*) AS transacoes,
        count(*) FILTER (WHERE e_gasto AND origem_da_categoria = 'padrao') AS sem_categoria,
        count(*) FILTER (WHERE e_gasto AND valor_brl IS NULL) AS sem_conversao,
        count(*) FILTER (WHERE compra_pendente) AS parcelas_pendentes
    FROM transacoes_analiticas GROUP BY instituicao
)
SELECT i.instituicao, t.primeira_transacao, t.ultima_transacao, p.data_posicao,
    r.ultima_ingestao, coalesce(c.contas, 0) AS contas, coalesce(t.transacoes, 0) AS transacoes,
    coalesce(t.sem_categoria, 0) AS sem_categoria, coalesce(t.sem_conversao, 0) AS sem_conversao,
    coalesce(t.parcelas_pendentes, 0) AS parcelas_pendentes,
    CASE WHEN t.ultima_transacao IS NOT NULL THEN 'dados_observados' ELSE 'sem_movimento' END AS situacao,
    s.sucesso_em AS ultima_sincronizacao, coalesce(s.estado, 'sem_registro') AS sincronizacao_estado,
    s.desde AS cobertura_desde, s.ate AS cobertura_ate
FROM instituicoes i LEFT JOIN contas c USING (instituicao)
LEFT JOIN transacoes t USING (instituicao) LEFT JOIN tempos r USING (instituicao)
LEFT JOIN posicoes p USING (instituicao)
LEFT JOIN log_sincronizacoes s USING (instituicao);
