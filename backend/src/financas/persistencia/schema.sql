-- Schema da camada raw e das tabelas de configuração.
--
-- Duas famílias de tabela vivem aqui:
--
--   raw_*  fiel ao que a API devolveu. Nenhuma regra de negócio aplicada.
--   cfg_*  espelho do config/regras.toml, para as views SQL fazerem JOIN em vez
--          de carregarem padrão hardcoded.
--
-- Sobre chave natural, que é a decisão mais importante deste arquivo:
--
--   Transação é EVENTO. Aconteceu uma vez, tem id próprio e estável. Chave: id.
--
--   Conta e investimento são ESTADO. O saldo de hoje não é o de ontem. Se a
--   chave fosse só o id, cada ingestão sobrescreveria o retrato anterior e o
--   histórico de patrimônio nunca existiria — não dá para reconstruir depois um
--   dado que nunca foi gravado. Por isso a chave é (id, data_posicao): uma
--   linha por conta por dia.
--
-- Sobre tipos: dinheiro é DECIMAL, nunca DOUBLE. Soma de ponto flutuante
-- acumula erro de arredondamento e o total do mês precisa fechar com o extrato.
--
-- Sobre ingerido_em / atualizado_em: o primeiro é gravado uma vez e nunca mais
-- tocado; o segundo só se mexe quando o payload realmente mudou. Ver banco.py.

-- ---------------------------------------------------------------------------
-- Transações — chave natural: id
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raw_transacoes (
    id                    VARCHAR       NOT NULL,
    id_conta              VARCHAR       NOT NULL,
    -- Guardado como atributo, jamais como chave: reautorizar no Open Finance
    -- gera um id_item novo para a mesma instituição (armadilha 8).
    id_item               VARCHAR,
    -- Procedência, propagada na travessia item -> conta -> transação. A API não
    -- devolve isso junto da transação, e sem ele não dá para aplicar padrão de
    -- fatura por instituição.
    instituicao           VARCHAR,
    descricao             VARCHAR,
    descricao_original    VARCHAR,
    valor                 DECIMAL(18,2),
    moeda                 VARCHAR,
    data                  DATE,
    tipo                  VARCHAR,       -- DEBIT | CREDIT
    situacao              VARCHAR,       -- POSTED | PENDING
    categoria             VARCHAR,       -- categoria da Pluggy; a própria vem na fase 2
    id_categoria          VARCHAR,
    saldo                 DECIMAL(18,2),
    -- Campos de contraparte: é com eles que a armadilha 2 identifica
    -- transferência entre contas do próprio titular.
    metodo_pagamento      VARCHAR,
    pagador_nome          VARCHAR,
    pagador_documento     VARCHAR,
    recebedor_nome        VARCHAR,
    recebedor_documento   VARCHAR,
    recebedor_chave_pix   VARCHAR,
    estabelecimento_nome  VARCHAR,
    estabelecimento_cnpj  VARCHAR,
    cartao_final          VARCHAR,
    parcela_numero        INTEGER,
    parcela_total         INTEGER,
    payload_json          VARCHAR       NOT NULL,
    ingerido_em           TIMESTAMP     NOT NULL,
    atualizado_em         TIMESTAMP     NOT NULL,
    PRIMARY KEY (id)
);

-- ---------------------------------------------------------------------------
-- Contas — chave natural: (id, data_posicao). Um retrato por dia.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raw_contas (
    id                    VARCHAR       NOT NULL,
    data_posicao          DATE          NOT NULL,
    id_item               VARCHAR,
    instituicao           VARCHAR,
    tipo                  VARCHAR,       -- BANK | CREDIT
    subtipo               VARCHAR,
    nome                  VARCHAR,
    nome_comercial        VARCHAR,
    numero                VARCHAR,
    saldo                 DECIMAL(18,2),
    moeda                 VARCHAR,
    titular               VARCHAR,
    limite_credito        DECIMAL(18,2),
    limite_disponivel     DECIMAL(18,2),
    fechamento_fatura     DATE,
    vencimento_fatura     DATE,
    payload_json          VARCHAR       NOT NULL,
    ingerido_em           TIMESTAMP     NOT NULL,
    atualizado_em         TIMESTAMP     NOT NULL,
    PRIMARY KEY (id, data_posicao)
);

-- ---------------------------------------------------------------------------
-- Investimentos — chave natural: (id, data_posicao).
--
-- Armadilha 3: aporte não é despesa. Esta tabela não tem relação nenhuma com
-- raw_transacoes, de propósito. Somar as duas é o erro que ela previne.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raw_investimentos (
    id                    VARCHAR       NOT NULL,
    -- Data da ingestão, igual a raw_contas. É o que mantém as duas séries
    -- alinhadas para a view `patrimonio` somar as duas no mesmo dia.
    data_posicao          DATE          NOT NULL,
    -- Data que a corretora informa, normalmente o fechamento do mês.
    -- Informativa: não entra na chave, senão o calendário divergiria de contas.
    data_referencia       DATE,
    id_item               VARCHAR,
    instituicao           VARCHAR,
    nome                  VARCHAR,
    numero                VARCHAR,
    tipo                  VARCHAR,
    subtipo               VARCHAR,
    emissor               VARCHAR,
    moeda                 VARCHAR,
    data_aplicacao        DATE,
    data_vencimento       DATE,
    taxa                  DECIMAL(18,6),
    tipo_taxa             VARCHAR,
    quantidade            DECIMAL(18,8),
    valor_aplicado        DECIMAL(18,2),
    saldo                 DECIMAL(18,2),
    rendimento            DECIMAL(18,2),
    situacao              VARCHAR,
    payload_json          VARCHAR       NOT NULL,
    ingerido_em           TIMESTAMP     NOT NULL,
    atualizado_em         TIMESTAMP     NOT NULL,
    PRIMARY KEY (id, data_posicao)
);

-- ---------------------------------------------------------------------------
-- Configuração — espelho do config/regras.toml
--
-- Reescritas por inteiro a cada carga. Existem para que as views não precisem
-- de string templating: o filtro vira JOIN, e o .sql versionado continua
-- executável e legível sozinho.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS cfg_padroes_fatura (
    instituicao           VARCHAR       NOT NULL,  -- padrão LIKE, '%' vale para todas
    padrao                VARCHAR       NOT NULL,  -- sintaxe LIKE, em minúsculas
    observacao            VARCHAR
);

-- Armadilha 3: aplicação que sai da conta corrente para um investimento aparece
-- como débito em BANK, não pelo contexto Investments. Não é despesa: o dinheiro
-- continua sendo seu, só mudou de lugar.
CREATE TABLE IF NOT EXISTS cfg_padroes_aplicacao (
    instituicao           VARCHAR       NOT NULL,  -- padrão LIKE, '%' vale para todas
    padrao                VARCHAR       NOT NULL,  -- sintaxe LIKE, em minúsculas
    observacao            VARCHAR
);

CREATE TABLE IF NOT EXISTS cfg_contrapartes_proprias (
    tipo                  VARCHAR       NOT NULL,  -- titular | chave_pix | contraparte
    valor                 VARCHAR       NOT NULL,  -- sintaxe LIKE, em minúsculas
    observacao            VARCHAR
);

CREATE TABLE IF NOT EXISTS cfg_frescor (
    instituicao           VARCHAR       NOT NULL,
    dias_maximos          INTEGER       NOT NULL,
    observacao            VARCHAR
);

CREATE TABLE IF NOT EXISTS cfg_geral (
    chave                 VARCHAR       NOT NULL,
    valor                 VARCHAR       NOT NULL,
    PRIMARY KEY (chave)
);

-- ---------------------------------------------------------------------------
-- Fase 2: categorização própria
--
-- A categoria que a Pluggy devolve é grosseira ("Shopping" não diz nada) e não
-- se pode editar. A resolução acontece em três camadas, em stg_transacoes:
--
--   1. cfg_categorias       regra por texto, a mais precisa            vence
--   2. cfg_mapa_categorias  de-para do categoryId, cobre o resto
--   3. cfg_geral            rótulo padrão, para o que sobrou
--
-- Sozinha, a camada 1 deixa buraco, e buraco vira "outros" crescendo em
-- silêncio. Sozinha, a 2 cobre tudo mas é grosseira demais onde importa.
-- ---------------------------------------------------------------------------

-- PRIMARY KEY em prioridade não é enfeite: é o que impede duas regras de
-- empatarem. Com empate, a regra vencedora passaria a depender da ordem das
-- linhas do TOML — e o relatório mudaria sozinho quando alguém reordenasse o
-- arquivo, sem nenhum teste acusar.
CREATE TABLE IF NOT EXISTS cfg_categorias (
    prioridade            INTEGER       NOT NULL,  -- menor vence
    instituicao           VARCHAR       NOT NULL,  -- padrão LIKE, '%' vale para todas
    padrao                VARCHAR       NOT NULL,  -- padrão LIKE, em minúsculas
    categoria             VARCHAR       NOT NULL,  -- rótulo de saída, como escrito
    grupo                 VARCHAR       NOT NULL,  -- rótulo de saída, como escrito
    observacao            VARCHAR,
    PRIMARY KEY (prioridade)
);

-- Casa por igualdade, não por LIKE: o conjunto de categorias da Pluggy é finito
-- e conhecido, então a igualdade elimina por construção a chance de duas linhas
-- casarem a mesma transação.
CREATE TABLE IF NOT EXISTS cfg_mapa_categorias (
    id_categoria          VARCHAR       NOT NULL,  -- categoryId da Pluggy, ex.: 05070000
    categoria             VARCHAR       NOT NULL,
    grupo                 VARCHAR       NOT NULL,
    observacao            VARCHAR,
    PRIMARY KEY (id_categoria)
);
