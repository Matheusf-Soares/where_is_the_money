-- stg_transacoes: limpeza, tipagem e classificação de ruído.
--
-- Esta view não decide o que é gasto — ela só marca. Cada transação ganha três
-- bandeiras (`e_pagamento_de_fatura`, `e_transferencia_propria`, `e_aplicacao`)
-- e a view `gastos` decide o que fazer com elas.
--
-- A separação importa: quem quiser auditar "por que essa transação sumiu do
-- meu total?" consulta stg_transacoes e vê a bandeira que a excluiu, em vez de
-- caçar o filtro dentro de um WHERE.
--
-- Nenhum padrão está escrito aqui. Tudo vem das tabelas cfg_*, que são o
-- espelho do config/regras.toml.

CREATE OR REPLACE VIEW stg_transacoes AS
WITH base AS (
    SELECT
        id                                          AS id_transacao,
        id_conta,
        id_item,
        instituicao,
        data,
        -- A Pluggy às vezes só preenche descriptionRaw. Cair para ele evita
        -- perder a única pista textual que a transação tem.
        coalesce(descricao, descricao_original, '')  AS descricao,
        valor,
        moeda,
        tipo,
        situacao,
        categoria,
        estabelecimento_nome                        AS estabelecimento,
        estabelecimento_cnpj,
        cartao_final,
        parcela_numero,
        parcela_total,
        metodo_pagamento,
        recebedor_nome,
        recebedor_chave_pix,

        lower(coalesce(descricao, descricao_original, ''))  AS descricao_busca,
        lower(coalesce(instituicao, ''))                    AS instituicao_busca,
        lower(coalesce(pagador_nome, ''))                   AS pagador_busca,
        lower(coalesce(recebedor_nome, ''))                 AS recebedor_busca,
        lower(coalesce(recebedor_chave_pix, ''))            AS chave_busca,
        lower(coalesce(pagador_documento, ''))              AS documento_pagador_busca,
        lower(coalesce(recebedor_documento, ''))            AS documento_recebedor_busca
    FROM raw_transacoes
    -- Transação cancelada nunca movimentou dinheiro.
    WHERE coalesce(situacao, '') <> 'CANCELLED'
)
SELECT
    b.id_transacao,
    b.id_conta,
    b.id_item,
    b.instituicao,
    b.data,
    -- EXTRACT em vez de date_trunc: date_trunc tem assinatura diferente no
    -- BigQuery, e a migração está no radar. Ano e mês separados formatam em
    -- qualquer lugar.
    EXTRACT(YEAR FROM b.data)   AS ano,
    EXTRACT(MONTH FROM b.data)  AS mes,
    b.descricao,
    b.valor,
    b.moeda,
    b.tipo,
    b.situacao,
    b.categoria,
    b.estabelecimento,
    b.estabelecimento_cnpj,
    b.cartao_final,
    b.parcela_numero,
    b.parcela_total,
    b.metodo_pagamento,

    -- Armadilha 1: pagamento de fatura de cartão.
    EXISTS (
        SELECT 1 FROM cfg_padroes_fatura f
        WHERE b.instituicao_busca LIKE f.instituicao
          AND b.descricao_busca   LIKE f.padrao
    ) AS e_pagamento_de_fatura,

    -- Armadilha 2: transferência entre contas do próprio titular.
    --
    -- O campo onde procurar depende do tipo, e não é enfeite: procurar o nome
    -- do titular dentro de um número de documento gera falso positivo, e uma
    -- chave Pix nunca aparece no campo de nome.
    EXISTS (
        SELECT 1 FROM cfg_contrapartes_proprias c
        WHERE (
            c.tipo = 'titular' AND (
                b.pagador_busca   LIKE c.valor OR
                b.recebedor_busca LIKE c.valor OR
                b.descricao_busca LIKE c.valor
            )
        ) OR (
            -- A chave costuma vir no campo próprio, mas várias instituições só
            -- a escrevem no meio da descrição.
            c.tipo = 'chave_pix' AND (
                b.chave_busca     LIKE c.valor OR
                b.descricao_busca LIKE c.valor
            )
        ) OR (
            c.tipo = 'contraparte' AND (
                b.documento_pagador_busca   LIKE c.valor OR
                b.documento_recebedor_busca LIKE c.valor OR
                b.descricao_busca           LIKE c.valor
            )
        )
    ) AS e_transferencia_propria,

    -- Armadilha 3: aporte ou resgate. O dinheiro mudou de lugar, não sumiu.
    EXISTS (
        SELECT 1 FROM cfg_padroes_aplicacao a
        WHERE b.instituicao_busca LIKE a.instituicao
          AND b.descricao_busca   LIKE a.padrao
    ) AS e_aplicacao
FROM base b;
