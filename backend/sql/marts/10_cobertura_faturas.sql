-- Ausência de resposta não significa fatura de valor zero.
CREATE OR REPLACE VIEW cobertura_faturas AS
WITH contas AS (
    SELECT *, row_number() OVER (PARTITION BY id ORDER BY data_posicao DESC) AS posicao
    FROM raw_contas
)
SELECT c.id AS id_conta, c.instituicao, c.nome AS conta, c.numero AS numero_cartao,
    coalesce(l.estado, 'nao_coletado') AS estado, l.coletado_em, l.tentado_em,
    coalesce(l.mensagem, '') AS mensagem, l.transacoes_em, l.transacoes_desde
FROM contas c
LEFT JOIN log_faturas l ON l.id_conta = c.id
WHERE c.posicao = 1 AND upper(c.tipo) = 'CREDIT';
