-- patrimonio: evolução do saldo total ao longo do tempo.
--
-- Uma linha por instituição por dia de ingestão. A série existe porque
-- raw_contas e raw_investimentos são retratos diários; se a chave natural
-- fosse só o id, esta view só saberia responder sobre hoje.
--
-- Composição do patrimônio líquido:
--
--     saldo em conta  (contas BANK)
--   + investido       (posição em raw_investimentos)
--   - fatura em aberto (contas CREDIT)
--   ------------------------------------------------
--   = patrimonio_liquido
--
-- SUPOSIÇÃO A CONFERIR: assume-se que `balance` de conta CREDIT é o valor
-- devido, positivo. Se a Pluggy devolver negativo para alguma instituição, o
-- sinal aqui inverte e o patrimônio fica inflado. Vale conferir na primeira
-- ingestão real, uma instituição por vez.
--
-- Aqui não entra transação: aporte não é despesa e despesa não é patrimônio.
-- As duas metades do projeto se encontram só no relatório final.

CREATE OR REPLACE VIEW patrimonio AS
WITH contas AS (
    SELECT
        data_posicao,
        instituicao,
        sum(CASE WHEN tipo = 'CREDIT' THEN 0 ELSE coalesce(saldo, 0) END) AS saldo_em_conta,
        sum(CASE WHEN tipo = 'CREDIT' THEN coalesce(saldo, 0) ELSE 0 END) AS fatura_em_aberto
    FROM stg_contas
    GROUP BY data_posicao, instituicao
),
investimentos AS (
    SELECT
        data_posicao,
        instituicao,
        sum(coalesce(saldo, 0))       AS investido,
        sum(coalesce(rendimento, 0))  AS rendimento
    FROM stg_investimentos
    GROUP BY data_posicao, instituicao
)
-- FULL OUTER: a Rico pode ter investimento sem conta corrente relevante, e a
-- maioria das instituições tem conta sem investimento nenhum.
SELECT
    coalesce(c.data_posicao, i.data_posicao)  AS data_posicao,
    coalesce(c.instituicao, i.instituicao)    AS instituicao,
    coalesce(c.saldo_em_conta, 0)             AS saldo_em_conta,
    coalesce(i.investido, 0)                  AS investido,
    coalesce(i.rendimento, 0)                 AS rendimento,
    coalesce(c.fatura_em_aberto, 0)           AS fatura_em_aberto,
    coalesce(c.saldo_em_conta, 0)
      + coalesce(i.investido, 0)
      - coalesce(c.fatura_em_aberto, 0)       AS patrimonio_liquido
FROM contas c
FULL OUTER JOIN investimentos i
    ON  c.data_posicao = i.data_posicao
    AND c.instituicao  = i.instituicao
ORDER BY 1, 2;
