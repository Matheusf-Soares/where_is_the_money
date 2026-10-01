-- Prévia sempre parcial. Nenhum saldo/limite substitui o total oficial /bills.
CREATE OR REPLACE VIEW faturas_abertas AS
WITH fechadas AS (
    SELECT id_conta, max(fechamento) AS ultimo_fechamento,
        max(mes_referencia) AS ultimo_mes_fechado
    FROM faturas
    WHERE fechamento <= current_date OR (fechamento IS NULL AND vencimento <= current_date)
    GROUP BY id_conta
), resumo AS (
    SELECT id_conta,
        min(mes_previsao_fonte) FILTER (WHERE incluida_previa AND NOT previsao_inconsistente) AS mes_previsao_valida,
        min(mes_previsao_fonte) FILTER (WHERE incluida_previa) AS mes_previsao_observada,
        count(*) FILTER (WHERE incluida_previa) AS qtd_lancamentos,
        count(*) FILTER (WHERE incluida_previa AND valor_brl IS NOT NULL
            AND tipo_lancamento IN ('despesa', 'credito')) AS qtd_valores_ciclo_brl,
        count(*) FILTER (WHERE incluida_previa AND valor_brl IS NOT NULL
            AND tipo_lancamento = 'pagamento') AS qtd_pagamentos_brl,
        count(*) FILTER (WHERE incluida_previa AND valor_brl IS NULL) AS qtd_sem_conversao,
        count(*) FILTER (WHERE incluida_previa AND tipo_lancamento = 'despesa') AS qtd_despesas,
        count(*) FILTER (WHERE incluida_previa AND tipo_lancamento = 'credito') AS qtd_creditos,
        count(*) FILTER (WHERE incluida_previa AND tipo_lancamento = 'pagamento') AS qtd_pagamentos,
        count(*) FILTER (WHERE classificacao_periodo = 'futura') AS qtd_futuras,
        count(*) FILTER (WHERE classificacao_periodo = 'sem_associacao') AS qtd_sem_associacao,
        count(*) FILTER (WHERE classificacao_periodo = 'anterior') AS qtd_anteriores,
        count(*) FILTER (WHERE previsao_inconsistente) AS qtd_previsao_inconsistente,
        sum(valor_brl) FILTER (WHERE incluida_previa AND tipo_lancamento = 'despesa') AS despesas,
        sum(valor_brl) FILTER (WHERE incluida_previa AND tipo_lancamento = 'credito') AS creditos,
        sum(valor_brl) FILTER (WHERE incluida_previa AND tipo_lancamento = 'pagamento') AS pagamentos,
        min(data) FILTER (WHERE incluida_previa) AS primeira_data,
        max(data) FILTER (WHERE incluida_previa) AS ultima_data
    FROM lancamentos_fatura_aberta GROUP BY id_conta
)
SELECT c.id_conta, c.instituicao, c.conta, c.numero_cartao,
    coalesce(r.mes_previsao_valida, r.mes_previsao_observada) AS mes_previsao_fonte,
    f.ultimo_fechamento, f.ultimo_mes_fechado,
    -- Pagamento conhecido não comprova despesas/créditos conhecidos do ciclo.
    CASE WHEN r.qtd_valores_ciclo_brl > 0 THEN coalesce(r.despesas, 0) END::DECIMAL(18,2) AS subtotal_despesas_brl,
    CASE WHEN r.qtd_valores_ciclo_brl > 0 THEN coalesce(r.creditos, 0) END::DECIMAL(18,2) AS subtotal_creditos_brl,
    CASE WHEN r.qtd_pagamentos_brl > 0 OR r.qtd_valores_ciclo_brl > 0
         THEN coalesce(r.pagamentos, 0) END::DECIMAL(18,2) AS pagamentos_brl,
    CASE WHEN r.qtd_valores_ciclo_brl > 0 THEN coalesce(r.despesas, 0) - coalesce(r.creditos, 0) END::DECIMAL(18,2) AS liquido_conhecido_brl,
    coalesce(r.qtd_lancamentos, 0) AS qtd_lancamentos,
    coalesce(r.qtd_sem_conversao, 0) AS qtd_sem_conversao,
    coalesce(r.qtd_despesas, 0) AS qtd_despesas,
    coalesce(r.qtd_creditos, 0) AS qtd_creditos,
    coalesce(r.qtd_pagamentos, 0) AS qtd_pagamentos,
    coalesce(r.qtd_futuras, 0) AS qtd_futuras,
    coalesce(r.qtd_sem_associacao, 0) AS qtd_sem_associacao,
    coalesce(r.qtd_anteriores, 0) AS qtd_anteriores,
    coalesce(r.qtd_previsao_inconsistente, 0) AS qtd_previsao_inconsistente,
    r.primeira_data, r.ultima_data,
    c.transacoes_em AS coletado_em, true AS previa_parcial
FROM cobertura_faturas c
LEFT JOIN fechadas f ON f.id_conta = c.id_conta
LEFT JOIN resumo r ON r.id_conta = c.id_conta;
