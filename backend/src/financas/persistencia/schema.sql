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

-- Faturas têm identidade oficial por cartão e não são inferidas do saldo.
CREATE TABLE IF NOT EXISTS raw_faturas (
    id VARCHAR NOT NULL,
    id_conta VARCHAR NOT NULL,
    id_item VARCHAR,
    instituicao VARCHAR,
    vencimento DATE,
    fechamento DATE,
    valor_total DECIMAL(18,2),
    moeda VARCHAR,
    pagamento_minimo DECIMAL(18,2),
    permite_parcelamento BOOLEAN,
    pagamentos_json VARCHAR,
    encargos_json VARCHAR,
    payload_json VARCHAR NOT NULL,
    ingerido_em TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP NOT NULL,
    PRIMARY KEY (id, id_conta)
);

CREATE TABLE IF NOT EXISTS log_faturas (
    id_conta VARCHAR PRIMARY KEY,
    estado VARCHAR NOT NULL,
    coletado_em TIMESTAMP,
    tentado_em TIMESTAMP NOT NULL,
    transacoes_em TIMESTAMP,
    transacoes_desde DATE,
    mensagem VARCHAR NOT NULL
);

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
    --
    -- Não há coluna de chave Pix porque a API não devolve uma: `paymentData`
    -- identifica a contraparte por nome e por documento, e é só isso que
    -- existe. Chave Pix, quando aparece, vem dentro do texto da descrição.
    metodo_pagamento      VARCHAR,
    pagador_nome          VARCHAR,
    pagador_documento     VARCHAR,
    recebedor_nome        VARCHAR,
    recebedor_documento   VARCHAR,
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

-- Saldo da fatura anterior relançado na seguinte ("Saldo em atraso", "Saldo em
-- rotativo"). As compras já foram contadas quando aconteceram; o saldo é a mesma
-- despesa de novo. Sem reforço por categoria de propósito: a Pluggy põe juros e
-- multa na mesma categoria, e esses são custo real.
CREATE TABLE IF NOT EXISTS cfg_padroes_saldo_anterior (
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
-- A Pluggy classifica nativamente `Credit card payment`, `Same person transfer`
-- e `Investments` — exatamente as armadilhas 1, 2 e 3. Esta tabela deixa essa
-- classificação REFORÇAR a bandeira, nunca substituí-la: em stg_transacoes o
-- casamento é por OR com o padrão de texto.
--
-- Por que complementar e não substituir: categorização por ML erra, e o texto
-- pega o que ela errar. Trocar um pelo outro só mudaria o tipo de falso
-- negativo. E se a feature de categorização estiver desligada na conta, a
-- coluna vem nula e o filtro por texto continua sendo tudo que existe.
CREATE TABLE IF NOT EXISTS cfg_categorias_ruido (
    bandeira              VARCHAR       NOT NULL,  -- fatura | transferencia_propria | aplicacao
    padrao                VARCHAR       NOT NULL,  -- padrão LIKE sobre a categoria, em minúsculas
    observacao            VARCHAR
);

CREATE TABLE IF NOT EXISTS cfg_mapa_categorias (
    id_categoria          VARCHAR       NOT NULL,  -- categoryId da Pluggy, ex.: 05070000
    categoria             VARCHAR       NOT NULL,
    grupo                 VARCHAR       NOT NULL,
    observacao            VARCHAR,
    PRIMARY KEY (id_categoria)
);

-- Personalizações não são espelho do TOML e nunca são reescritas pela ingestão.
CREATE TABLE IF NOT EXISTS usr_categorias (
    id VARCHAR PRIMARY KEY, nome VARCHAR NOT NULL, macro_categoria VARCHAR NOT NULL,
    essencialidade VARCHAR NOT NULL DEFAULT 'nao_definido',
    comportamento VARCHAR NOT NULL DEFAULT 'nao_definido'
);
CREATE TABLE IF NOT EXISTS usr_classificacoes (
    id_transacao VARCHAR PRIMARY KEY, id_categoria VARCHAR NOT NULL
);
CREATE SEQUENCE IF NOT EXISTS usr_historico_seq START 1;
CREATE TABLE IF NOT EXISTS usr_historico_classificacoes (
    id BIGINT PRIMARY KEY DEFAULT nextval('usr_historico_seq'),
    id_transacao VARCHAR NOT NULL, id_categoria_anterior VARCHAR,
    id_categoria_nova VARCHAR NOT NULL, criado_em TIMESTAMP DEFAULT current_timestamp,
    desfeito_em TIMESTAMP
);
CREATE TABLE IF NOT EXISTS usr_regras (
    id VARCHAR PRIMARY KEY, prioridade INTEGER UNIQUE NOT NULL, padrao VARCHAR NOT NULL,
    instituicao VARCHAR NOT NULL, id_categoria VARCHAR NOT NULL, ativa BOOLEAN NOT NULL
);
CREATE TABLE IF NOT EXISTS usr_atributos (
    id_transacao VARCHAR PRIMARY KEY, essencialidade VARCHAR NOT NULL,
    comportamento VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS usr_estado (
    id INTEGER PRIMARY KEY CHECK (id = 1), revisao BIGINT NOT NULL
);
INSERT INTO usr_estado VALUES (1, 0) ON CONFLICT DO NOTHING;
CREATE SEQUENCE IF NOT EXISTS seq_historico_atributos;
CREATE TABLE IF NOT EXISTS usr_historico_atributos (
    id BIGINT DEFAULT nextval('seq_historico_atributos') PRIMARY KEY,
    id_transacao VARCHAR NOT NULL, anterior JSON, novos JSON NOT NULL,
    criado_em TIMESTAMP DEFAULT current_timestamp, desfeito_em TIMESTAMP
);
CREATE TABLE IF NOT EXISTS usr_mapas (
    id_categoria_pluggy VARCHAR PRIMARY KEY, id_categoria VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS usr_aliases (
    descricao_original VARCHAR NOT NULL, instituicao VARCHAR NOT NULL,
    estabelecimento VARCHAR NOT NULL, PRIMARY KEY(descricao_original, instituicao)
);
CREATE TABLE IF NOT EXISTS usr_recorrencias (
    instituicao VARCHAR NOT NULL, estabelecimento VARCHAR NOT NULL,
    estado VARCHAR NOT NULL, PRIMARY KEY(instituicao, estabelecimento)
);
CREATE TABLE IF NOT EXISTS usr_compras (
    id VARCHAR PRIMARY KEY, data_compra DATE NOT NULL, valor_total_brl DECIMAL(18,2) NOT NULL,
    descricao VARCHAR NOT NULL, grupo_parcial BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS usr_compra_transacoes (
    id_transacao VARCHAR PRIMARY KEY, id_compra VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS log_sincronizacoes (
    instituicao VARCHAR PRIMARY KEY, tentado_em TIMESTAMP, sucesso_em TIMESTAMP,
    desde DATE, ate DATE, estado VARCHAR, mensagem VARCHAR
);

INSERT INTO usr_categorias (id, nome, macro_categoria)
SELECT id, nome, macro_categoria FROM (VALUES
    ('alimentacao-geral', 'Geral', 'Alimentação'),
    ('alimentacao-mercado', 'Mercado', 'Alimentação'),
    ('alimentacao-delivery', 'Delivery', 'Alimentação'),
    ('alimentacao-restaurantes', 'Restaurantes', 'Alimentação'),
    ('moradia-geral', 'Geral', 'Moradia'),
    ('moradia-aluguel', 'Aluguel', 'Moradia'),
    ('moradia-contas', 'Contas da casa', 'Moradia'),
    ('transporte-geral', 'Geral', 'Transporte'),
    ('transporte-combustivel', 'Combustível', 'Transporte'),
    ('transporte-aplicativo', 'Transporte por aplicativo', 'Transporte'),
    ('transporte-publico', 'Transporte público', 'Transporte'),
    ('saude-geral', 'Geral', 'Saúde'),
    ('saude-academia', 'Academia', 'Saúde'),
    ('saude-farmacia', 'Farmácia', 'Saúde'),
    ('saude-consultas', 'Consultas', 'Saúde'),
    ('educacao-geral', 'Geral', 'Educação'),
    ('educacao-cursos', 'Cursos', 'Educação'),
    ('lazer-geral', 'Geral', 'Lazer'),
    ('lazer-streaming', 'Streaming', 'Lazer'),
    ('lazer-viagens', 'Viagens', 'Lazer'),
    ('compras-pessoais-geral', 'Geral', 'Compras pessoais'),
    ('compras-pessoais-vestuario', 'Vestuário', 'Compras pessoais'),
    ('servicos-geral', 'Geral', 'Serviços'),
    ('impostos-tarifas-geral', 'Geral', 'Impostos e tarifas'),
    ('doacoes-presentes-geral', 'Geral', 'Doações e presentes')
) AS sementes(id, nome, macro_categoria)
ON CONFLICT DO NOTHING;
