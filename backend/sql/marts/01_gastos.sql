-- gastos: o contrato público do backend.
--
-- Uma linha por transação que conta como gasto de verdade. É esta view que o
-- frontend da fase 3 vai consumir, então o grão é a transação — agregação por
-- mês, categoria ou estabelecimento é trivial em cima disso, e o caminho
-- inverso é impossível.
--
-- Três exclusões, todas configuráveis via cfg_*, nenhuma hardcoded:
--
--   1. Pagamento de fatura de cartão. A compra já está na conta CREDIT; o
--      pagamento na conta BANK é a mesma despesa contada de novo.
--   2. Transferência entre contas próprias. Mover dinheiro de um bolso para o
--      outro não é gasto.
--   3. Aplicação e resgate. O dinheiro mudou de lugar, não sumiu.
--
-- Sinal: `valor` aqui é POSITIVO. Na camada raw um gasto de R$ 100 é -100,
-- porque é assim que a API manda. Somar despesa negativa é fonte constante de
-- erro de sinal em relatório, então a inversão acontece uma vez, aqui.

CREATE OR REPLACE VIEW gastos AS
SELECT
    t.id_transacao,
    t.data,
    t.ano,
    t.mes,
    t.instituicao,
    -- De qual conta saiu: BANK ou CREDIT. Vem do retrato mais recente, então
    -- conta encerrada deixa o campo nulo em vez de sumir com a transação.
    c.tipo                                  AS tipo_de_conta,
    c.nome                                  AS conta,
    t.descricao,
    -- Fase 2. `categoria` é a SUA, resolvida em stg_transacoes pelas três
    -- camadas; `categoria_pluggy` é a que a API devolveu, mantida ao lado para
    -- auditar o de-para e descobrir id que ainda falta mapear.
    t.categoria,
    t.grupo,
    t.categoria_pluggy,
    t.origem_da_categoria,
    coalesce(t.estabelecimento, t.descricao) AS estabelecimento,
    -t.valor                                AS valor,
    t.moeda,
    t.cartao_final,
    t.parcela_numero,
    t.parcela_total,
    t.parcela_total IS NOT NULL AND t.parcela_total > 1  AS e_parcelado
FROM stg_transacoes t
LEFT JOIN stg_contas c
       ON c.id_conta = t.id_conta
      AND c.e_retrato_atual
WHERE t.valor < 0
  AND NOT t.e_pagamento_de_fatura
  AND NOT t.e_transferencia_propria
  AND NOT t.e_aplicacao;
