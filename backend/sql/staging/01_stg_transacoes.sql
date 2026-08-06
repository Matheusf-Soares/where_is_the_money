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
-- Ela também resolve a categoria própria (fase 2), em três camadas: regra por
-- texto, de-para do categoryId da Pluggy, e um rótulo padrão para o resto. A
-- coluna `origem_da_categoria` diz qual camada decidiu — pelo mesmo motivo das
-- bandeiras, auditar deve ser um SELECT e não uma caçada.
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
        -- categoryId da Pluggy. É hierárquico (05070000 = Streaming dentro de
        -- 05), e é a chave do de-para da fase 2.
        id_categoria,
        estabelecimento_nome                        AS estabelecimento,
        estabelecimento_cnpj,
        cartao_final,
        parcela_numero,
        parcela_total,
        metodo_pagamento,
        recebedor_nome,
        recebedor_chave_pix,

        lower(coalesce(descricao, descricao_original, ''))  AS descricao_busca,
        lower(coalesce(estabelecimento_nome, ''))           AS estabelecimento_busca,
        -- Vazio quando a Pluggy não classificou (feature premium desligada, ou
        -- transação que o modelo não reconheceu). Vazio não casa padrão nenhum,
        -- então o reforço por categoria simplesmente não atua — e o filtro por
        -- texto continua sendo tudo que existe.
        lower(coalesce(categoria, ''))                      AS categoria_busca,
        lower(coalesce(instituicao, ''))                    AS instituicao_busca,
        lower(coalesce(pagador_nome, ''))                   AS pagador_busca,
        lower(coalesce(recebedor_nome, ''))                 AS recebedor_busca,
        lower(coalesce(recebedor_chave_pix, ''))            AS chave_busca,
        lower(coalesce(pagador_documento, ''))              AS documento_pagador_busca,
        lower(coalesce(recebedor_documento, ''))            AS documento_recebedor_busca
    FROM raw_transacoes
    -- Transação cancelada nunca movimentou dinheiro.
    WHERE coalesce(situacao, '') <> 'CANCELLED'
),

-- Fase 2, camada 1: regra por texto.
--
-- Casa contra a descrição OU o estabelecimento, porque a Pluggy preenche um ou
-- outro conforme a instituição. Várias regras podem casar a mesma transação; o
-- row_number resolve pela prioridade, e a unicidade de `prioridade` (PRIMARY
-- KEY em cfg_categorias) garante que esse desempate é determinístico.
regra_casada AS (
    SELECT
        b.id_transacao,
        r.categoria,
        r.grupo,
        row_number() OVER (
            PARTITION BY b.id_transacao ORDER BY r.prioridade
        ) AS posicao
    FROM base b
    JOIN cfg_categorias r
      ON b.instituicao_busca LIKE r.instituicao
     AND (
            b.descricao_busca       LIKE r.padrao
         OR b.estabelecimento_busca LIKE r.padrao
     )
),

-- Camada 3: os rótulos de quem não casou com nada. Vêm de cfg_geral em vez de
-- literal aqui, para poderem ser renomeados sem editar esta view.
rotulos AS (
    SELECT
        max(CASE WHEN chave = 'categoria_padrao' THEN valor END) AS categoria_padrao,
        max(CASE WHEN chave = 'grupo_padrao'     THEN valor END) AS grupo_padrao
    FROM cfg_geral
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
    -- Nomenclatura, válida no projeto inteiro: `categoria` é SEMPRE a sua, e
    -- `categoria_pluggy` é SEMPRE a que a API devolveu. A da Pluggy continua
    -- ao lado para auditar o de-para — dá para ver o que a fonte dizia e o que
    -- virou.
    b.categoria      AS categoria_pluggy,
    b.id_categoria,

    -- Fase 2: a categoria própria, resolvida nas três camadas.
    --
    -- O coalesce é a resolução inteira: regra por texto, senão de-para do
    -- categoryId, senão o rótulo padrão. Nunca NULL — categoria que some de um
    -- GROUP BY é gasto que desaparece do relatório sem ninguém notar.
    coalesce(rc.categoria, m.categoria, r.categoria_padrao)  AS categoria,
    coalesce(rc.grupo,     m.grupo,     r.grupo_padrao)      AS grupo,

    -- De qual camada veio. Sem isso, "por que essa transação está em Lazer?"
    -- vira caçada; com isso, é uma coluna. Mesma lógica das três bandeiras.
    CASE
        WHEN rc.categoria IS NOT NULL THEN 'regra'
        WHEN m.categoria  IS NOT NULL THEN 'mapa'
        ELSE 'padrao'
    END                                                      AS origem_da_categoria,

    b.estabelecimento,
    b.estabelecimento_cnpj,
    b.cartao_final,
    b.parcela_numero,
    b.parcela_total,
    b.metodo_pagamento,

    -- Armadilha 1: pagamento de fatura de cartão.
    --
    -- Texto OU categoria. A segunda metade cobre a redação que ninguém previu —
    -- o dia em que o Santander trocar "PAGTO CARTAO" por outra coisa, a
    -- categoria `Credit card payment` continua marcando.
    (
        EXISTS (
            SELECT 1 FROM cfg_padroes_fatura f
            WHERE b.instituicao_busca LIKE f.instituicao
              AND b.descricao_busca   LIKE f.padrao
        )
        OR EXISTS (
            SELECT 1 FROM cfg_categorias_ruido c
            WHERE c.bandeira = 'fatura'
              AND b.categoria_busca LIKE c.padrao
        )
    ) AS e_pagamento_de_fatura,

    -- Armadilha 2: transferência entre contas do próprio titular.
    --
    -- O campo onde procurar depende do tipo, e não é enfeite: procurar o nome
    -- do titular dentro de um número de documento gera falso positivo, e uma
    -- chave Pix nunca aparece no campo de nome.
    --
    -- Aqui o reforço por categoria vale ainda mais: a lista de contrapartes
    -- depende de você ter escrito seu nome e cada chave Pix, em cada formato.
    -- `Same person transfer` não depende de nada disso.
    (
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
    )
    OR EXISTS (
        SELECT 1 FROM cfg_categorias_ruido c
        WHERE c.bandeira = 'transferencia_propria'
          AND b.categoria_busca LIKE c.padrao
    )
    ) AS e_transferencia_propria,

    -- Armadilha 3: aporte ou resgate. O dinheiro mudou de lugar, não sumiu.
    (
        EXISTS (
            SELECT 1 FROM cfg_padroes_aplicacao a
            WHERE b.instituicao_busca LIKE a.instituicao
              AND b.descricao_busca   LIKE a.padrao
        )
        OR EXISTS (
            SELECT 1 FROM cfg_categorias_ruido c
            WHERE c.bandeira = 'aplicacao'
              AND b.categoria_busca LIKE c.padrao
        )
    ) AS e_aplicacao
FROM base b
LEFT JOIN regra_casada rc
       ON rc.id_transacao = b.id_transacao
      AND rc.posicao = 1
LEFT JOIN cfg_mapa_categorias m
       ON m.id_categoria = b.id_categoria
CROSS JOIN rotulos r;
