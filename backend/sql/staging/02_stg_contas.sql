-- stg_contas: retratos diários de conta, com o mais recente sinalizado.
--
-- raw_contas guarda uma linha por conta por dia. Quase toda consulta quer só o
-- retrato de hoje, e quem quer a série histórica quer todos — daí a bandeira
-- `e_retrato_atual` em vez de a view já filtrar.

CREATE OR REPLACE VIEW stg_contas AS
SELECT
    id                              AS id_conta,
    data_posicao,
    id_item,
    instituicao,
    tipo,
    subtipo,
    coalesce(nome_comercial, nome)  AS nome,
    numero,
    saldo,
    moeda,
    titular,
    limite_credito,
    limite_disponivel,
    fechamento_fatura,
    vencimento_fatura,
    tipo = 'CREDIT'                 AS e_cartao,
    -- A janela sem PARTITION compara com o retrato mais novo do banco inteiro,
    -- e não por instituição: uma instituição que falhou na última ingestão não
    -- deve ficar com um retrato velho marcado como atual.
    data_posicao = max(data_posicao) OVER ()  AS e_retrato_atual
FROM raw_contas;
