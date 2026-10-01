-- billForecastDate identifica coortes da fonte, não um vencimento oficial.
-- Mantém excluídos/ambíguos disponíveis para auditoria; raw permanece intacto.
CREATE OR REPLACE VIEW lancamentos_fatura_aberta AS
WITH fechadas AS (
    SELECT id_conta, max(fechamento) AS ultimo_fechamento,
        max(mes_referencia) AS ultimo_mes_fechado
    FROM faturas
    WHERE fechamento <= current_date OR (fechamento IS NULL AND vencimento <= current_date)
    GROUP BY id_conta
), fonte AS (
    SELECT t.*, f.ultimo_fechamento, f.ultimo_mes_fechado,
        nullif(trim(json_extract_string(try_cast(r.payload_json AS JSON),
            '$.creditCardMetadata.billForecastDate')), '') AS previsao_original,
        json_extract_string(try_cast(r.payload_json AS JSON), '$.operationType') AS tipo_operacao_fonte
    FROM transacoes_analiticas t
    JOIN raw_transacoes r ON r.id = t.id_transacao
    LEFT JOIN fechadas f ON f.id_conta = t.id_conta
    WHERE upper(t.tipo_de_conta) = 'CREDIT' AND upper(t.situacao) = 'PENDING'
        AND nullif(trim(t.id_fatura), '') IS NULL
        -- Pendente já reemitida como lançada: o gêmeo lançado é que vale.
        AND NOT t.e_pendente_substituida
), previsoes AS (
    SELECT *, CASE WHEN length(previsao_original) = 7
            AND try_cast(previsao_original || '-01' AS DATE) IS NOT NULL
        THEN strftime(try_cast(previsao_original || '-01' AS DATE), '%Y-%m') END AS mes_previsao_fonte
    FROM fonte
), coortes AS (
    SELECT id_conta, min(mes_previsao_fonte) AS primeira_coorte
    FROM previsoes
    WHERE data <= current_date
        AND (ultimo_fechamento IS NULL OR data >= ultimo_fechamento)
        AND (ultimo_mes_fechado IS NULL OR mes_previsao_fonte > ultimo_mes_fechado)
    GROUP BY id_conta
), classificadas AS (
    SELECT p.* EXCLUDE (previsao_original),
        coalesce(mes_previsao_fonte <= ultimo_mes_fechado, false) AS previsao_inconsistente,
        CASE WHEN e_pagamento_de_fatura OR upper(tipo_operacao_fonte) = 'PAGAMENTO_FATURA'
                  OR (upper(tipo_operacao_fonte) = 'PAGAMENTO' AND valor_assinado > 0) THEN 'pagamento'
             WHEN valor_assinado < 0 THEN 'despesa'
             WHEN valor_assinado > 0 THEN 'credito'
             ELSE 'sem_valor' END AS tipo_lancamento,
        CASE WHEN data > current_date THEN 'futura'
             WHEN data < ultimo_fechamento THEN 'anterior'
             WHEN mes_previsao_fonte > c.primeira_coorte THEN 'futura'
             -- No dia de fechamento não há hora/corte: só a previsão posterior
             -- ao último mês fechado pode resolver a ambiguidade.
             WHEN data = ultimo_fechamento AND
                 (mes_previsao_fonte IS NULL OR ultimo_mes_fechado IS NULL
                  OR mes_previsao_fonte <= ultimo_mes_fechado) THEN 'sem_associacao'
             WHEN data IS NULL THEN 'sem_associacao'
             WHEN ultimo_fechamento IS NOT NULL THEN 'andamento'
             WHEN mes_previsao_fonte IS NOT NULL AND
                 (ultimo_mes_fechado IS NULL OR mes_previsao_fonte > ultimo_mes_fechado) THEN 'andamento'
             ELSE 'sem_associacao' END AS classificacao_periodo
    FROM previsoes p LEFT JOIN coortes c ON c.id_conta = p.id_conta
)
SELECT *, classificacao_periodo = 'andamento' AS incluida_previa FROM classificadas;
