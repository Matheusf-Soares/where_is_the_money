"""
Verificação de frescor dos dados (armadilha 4).

Quando o consentimento de Open Finance vence, o pipeline **não quebra**: ele
continua rodando, continua respondendo 200, e simplesmente para de trazer
transação nova. É o pior modo de falha possível, porque o relatório do mês
parece certo enquanto está faltando metade.

Este módulo compara, por instituição, a transação mais recente contra uma
tolerância em dias. A tolerância existe por causa da armadilha 5: conector
regulado tem latência de até 24h, então alertar no primeiro dia sem movimento
só geraria ruído.

A regra vive em SQL, casando `cfg_frescor` com `cfg_geral` — as duas carregadas
do `regras.toml`. Não há cópia dessa lógica em Python, de propósito: duas
implementações da mesma regra divergem.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from financas.persistencia import Banco

registrador = logging.getLogger(__name__)

# Instituições consideradas conectadas são as que apareceram no último snapshot
# de contas. Uma que sumiu do `/items` não deve gerar alerta eterno.
#
# O LEFT JOIN em raw_transacoes é essencial: instituição conectada que nunca
# trouxe transação nenhuma é justamente o caso mais grave, e um INNER JOIN a
# esconderia.
CONSULTA_DE_FRESCOR = """
WITH ultimo_retrato AS (
    SELECT max(data_posicao) AS data_posicao FROM raw_contas
),
conectadas AS (
    SELECT DISTINCT instituicao
    FROM raw_contas
    WHERE data_posicao = (SELECT data_posicao FROM ultimo_retrato)
),
movimento AS (
    -- `data <= hoje` não é detalhe: a API devolve as parcelas futuras de um
    -- parcelamento junto das demais, com data à frente. Sem o recorte, a
    -- última transação do Nubank era 2026-12-10 e o atraso saía NEGATIVO —
    -- toda instituição parecia fresca, inclusive a que tinha parado.
    SELECT instituicao, max(data) AS ultima
    FROM raw_transacoes
    WHERE data <= CAST($hoje AS DATE)
    GROUP BY instituicao
),
padrao AS (
    SELECT CAST(valor AS INTEGER) AS dias
    FROM cfg_geral
    WHERE chave = 'frescor_dias_padrao'
),
-- Um limite específico vence o padrão. `instituicao` em cfg_frescor é padrão
-- LIKE, porque o connector.name nem sempre é o nome curto ("Rico Investimentos").
limite AS (
    SELECT c.instituicao, min(f.dias_maximos) AS dias_maximos
    FROM conectadas c
    JOIN cfg_frescor f ON lower(c.instituicao) LIKE lower(f.instituicao)
    GROUP BY c.instituicao
)
SELECT
    c.instituicao,
    m.ultima                                              AS ultima_transacao,
    COALESCE(l.dias_maximos, (SELECT dias FROM padrao))   AS dias_maximos,
    date_diff('day', m.ultima, CAST($hoje AS DATE))       AS dias_de_atraso
FROM conectadas c
LEFT JOIN movimento m ON c.instituicao = m.instituicao
LEFT JOIN limite l    ON c.instituicao = l.instituicao
ORDER BY c.instituicao
"""


@dataclass(frozen=True)
class SituacaoDaInstituicao:
    """Diagnóstico de frescor de uma instituição."""

    instituicao: str
    ultima_transacao: date | None
    dias_maximos: int
    dias_de_atraso: int | None

    @property
    def fresca(self) -> bool:
        """Instituição sem nenhuma transação nunca é considerada fresca.

        É o caso mais suspeito de todos: a conexão existe, mas nada chegou.
        """
        if self.dias_de_atraso is None:
            return False
        return self.dias_de_atraso <= self.dias_maximos

    def descrever(self) -> str:
        if self.ultima_transacao is None:
            return f"{self.instituicao}: nenhuma transação ingerida"
        estado = "ok" if self.fresca else "ATRASADA"
        return (
            f"{self.instituicao}: última em {self.ultima_transacao} "
            f"({self.dias_de_atraso}d atrás, tolerância {self.dias_maximos}d) [{estado}]"
        )


def verificar_frescor(banco: Banco, *, hoje: date) -> list[SituacaoDaInstituicao]:
    """Diagnostica todas as instituições conectadas.

    Devolve lista vazia quando não há retrato de contas no banco — ou seja,
    quando a ingestão nunca rodou. Quem chama precisa distinguir "tudo fresco"
    de "não há o que avaliar"; dizer "ok" com o banco vazio seria mentira.
    """
    linhas = banco.conexao.execute(
        CONSULTA_DE_FRESCOR, {"hoje": hoje.isoformat()}
    ).fetchall()

    return [
        SituacaoDaInstituicao(
            instituicao=instituicao,
            ultima_transacao=ultima,
            dias_maximos=int(dias_maximos),
            dias_de_atraso=None if atraso is None else int(atraso),
        )
        for instituicao, ultima, dias_maximos, atraso in linhas
    ]


def atrasadas(
    situacoes: list[SituacaoDaInstituicao],
) -> list[SituacaoDaInstituicao]:
    return [situacao for situacao in situacoes if not situacao.fresca]
