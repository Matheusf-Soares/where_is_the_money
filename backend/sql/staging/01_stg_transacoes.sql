-- stg_transacoes: limpeza, tipagem e classificação de ruído.
--
-- Esta view não decide o que é gasto — ela só marca. Cada transação ganha as
-- bandeiras (`e_pagamento_de_fatura`, `e_transferencia_propria`, `e_aplicacao`,
-- `e_saldo_anterior`, `e_pendente_substituida`) e a view `gastos` decide o que
-- fazer com elas.
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
        -- O valor como a API mandou, preservado para auditoria.
        valor,
        -- O valor com sinal NORMALIZADO: saída sempre negativa.
        --
        -- Isto existe porque conta CREDIT inverte a convenção. No cartão, uma
        -- compra (`type=DEBIT`) vem com amount POSITIVO; na conta corrente vem
        -- negativo. Filtrar por `valor < 0` descartava todas as compras de
        -- cartão — silenciosamente, que é o pior jeito de errar um total.
        --
        -- `tipo` é o invariante: DEBIT é saída e CREDIT é entrada nas duas
        -- convenções. Quando `tipo` não vem, resta confiar no sinal cru.
        CASE
            WHEN upper(coalesce(tipo, '')) = 'DEBIT'  THEN -abs(valor)
            WHEN upper(coalesce(tipo, '')) = 'CREDIT' THEN  abs(valor)
            ELSE valor
        END                                          AS valor_assinado,
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

        lower(coalesce(descricao, descricao_original, ''))  AS descricao_busca,
        -- `description` é o texto JÁ PROCESSADO pela Pluggy; `descriptionRaw`
        -- é o original do banco. Padrão escrito olhando o extrato casa com o
        -- segundo, então os dois são consultados — procurar só no processado
        -- perderia exatamente os padrões que você copiou do seu extrato.
        lower(coalesce(descricao_original, ''))             AS original_busca,
        lower(coalesce(estabelecimento_nome, ''))           AS estabelecimento_busca,
        -- Vazio quando a Pluggy não classificou (feature premium desligada, ou
        -- transação que o modelo não reconheceu). Vazio não casa padrão nenhum,
        -- então o reforço por categoria simplesmente não atua — e o filtro por
        -- texto continua sendo tudo que existe.
        lower(coalesce(categoria, ''))                      AS categoria_busca,
        lower(coalesce(instituicao, ''))                    AS instituicao_busca,
        -- Direção do dinheiro, derivada do valor já normalizado. Decide qual
        -- lado da transação é a CONTRAPARTE: numa saída é o recebedor, numa
        -- entrada é o pagador.
        CASE
            WHEN upper(coalesce(tipo, '')) = 'DEBIT'  THEN TRUE
            WHEN upper(coalesce(tipo, '')) = 'CREDIT' THEN FALSE
            ELSE valor < 0
        END                                                 AS e_saida,
        lower(coalesce(pagador_nome, ''))                   AS pagador_busca,
        lower(coalesce(recebedor_nome, ''))                 AS recebedor_busca,
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
         OR b.original_busca        LIKE r.padrao
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
),

marcada AS (
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
    b.valor_assinado,
    b.moeda,
    b.tipo,
    b.situacao,
    -- Parcela que ainda não aconteceu. A Pluggy devolve as futuras de um
    -- parcelamento junto das demais, com `status = PENDING` e data à frente.
    -- Elas não são gasto: somá-las infla meses que ainda não chegaram.
    --
    -- Fica como bandeira, e não como WHERE, pelo mesmo motivo das outras três:
    -- "por que essa parcela não está no total?" se responde com um SELECT.
    b.data > current_date                            AS e_futura,
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
              AND (b.descricao_busca LIKE f.padrao OR b.original_busca LIKE f.padrao)
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
            -- A contraparte depende da direção. Casar o nome do titular
            -- contra o PAGADOR de um débito identifica você mesmo — e você é
            -- o pagador de todo gasto que faz. Essa inversão já marcou 147
            -- transações e R$ 102.191,93 como transferência própria.
            c.tipo = 'titular' AND (
                (b.e_saida     AND b.recebedor_busca LIKE c.valor) OR
                (NOT b.e_saida AND b.pagador_busca   LIKE c.valor) OR
                b.descricao_busca LIKE c.valor OR
                b.original_busca  LIKE c.valor
            )
        ) OR (
            -- A API não devolve a chave Pix em campo próprio — `paymentData` só
            -- traz nome e documento. Quando a chave aparece, é dentro do texto,
            -- então é no texto que se procura. Para casar por CPF prefira
            -- `tipo = "contraparte"`, que bate no documento estruturado.
            c.tipo = 'chave_pix' AND (
                b.descricao_busca LIKE c.valor OR
                b.original_busca  LIKE c.valor
            )
        ) OR (
            -- Mesma correção de direção, pelo mesmo motivo: o seu CPF é o
            -- documento do pagador em todo débito que você faz.
            c.tipo = 'contraparte' AND (
                (b.e_saida     AND b.documento_recebedor_busca LIKE c.valor) OR
                (NOT b.e_saida AND b.documento_pagador_busca   LIKE c.valor) OR
                b.descricao_busca LIKE c.valor OR
                b.original_busca  LIKE c.valor
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
              AND (b.descricao_busca LIKE a.padrao OR b.original_busca LIKE a.padrao)
        )
        OR EXISTS (
            SELECT 1 FROM cfg_categorias_ruido c
            WHERE c.bandeira = 'aplicacao'
              AND b.categoria_busca LIKE c.padrao
        )
    ) AS e_aplicacao,

    -- Saldo da fatura anterior relançado na seguinte ("Saldo em atraso", "Saldo
    -- em rotativo"). As compras já entraram no gasto quando aconteceram; contar
    -- o saldo de novo dobrava o mês. Só por texto: a Pluggy põe juros e multa
    -- na mesma categoria, e esses são custo de verdade.
    EXISTS (
        SELECT 1 FROM cfg_padroes_saldo_anterior s
        WHERE b.instituicao_busca LIKE s.instituicao
          AND (b.descricao_busca LIKE s.padrao OR b.original_busca LIKE s.padrao)
    ) AS e_saldo_anterior
FROM base b
LEFT JOIN regra_casada rc
       ON rc.id_transacao = b.id_transacao
      AND rc.posicao = 1
LEFT JOIN cfg_mapa_categorias m
       ON m.id_categoria = b.id_categoria
CROSS JOIN rotulos r
)
-- Pendente reemitida. A Pluggy lança a transação pendente com um id NOVO e a
-- pendente antiga continua no raw, que é sagrado e nunca apaga. As duas
-- contavam. O gêmeo é a lançada da mesma conta, com o mesmo valor, até três
-- dias de distância e o mesmo texto; pagamento de fatura troca o texto ao ser
-- lançado ("PAGAMENTO ON LINE" vira "Pagamento recebido"), então dois
-- pagamentos de fatura também casam. Dois abastecimentos de mesmo valor em
-- postos diferentes não casam: são dois gastos.
SELECT
    m.*,
    (
        upper(coalesce(m.situacao, '')) = 'PENDING'
        AND NOT m.e_futura
        AND EXISTS (
            SELECT 1 FROM marcada l
            WHERE l.id_conta = m.id_conta
              AND l.id_transacao <> m.id_transacao
              AND upper(coalesce(l.situacao, '')) = 'POSTED'
              AND l.valor_assinado = m.valor_assinado
              AND abs(date_diff('day', l.data, m.data)) <= 3
              AND (lower(l.descricao) = lower(m.descricao)
                   OR (l.e_pagamento_de_fatura AND m.e_pagamento_de_fatura))
        )
    ) AS e_pendente_substituida
FROM marcada m;
