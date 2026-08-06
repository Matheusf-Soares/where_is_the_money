"""
Testes da verificação de frescor (armadilha 4).

O cenário está plantado nas fixtures: o PicPay parou em 2025-08-06, as demais
instituições vão até meados de setembro. Com `hoje = 2025-09-20`, o PicPay está
45 dias atrasado e precisa ser apontado.
"""

from __future__ import annotations

from datetime import date

import pytest

from financas.config import Configuracao
from financas.frescor import atrasadas, verificar_frescor
from financas.ingestao import ingerir
from financas.persistencia import Banco
from financas.pluggy import criar_cliente

HOJE = date(2025, 9, 20)


@pytest.fixture
def banco_com_dados(banco: Banco, config_offline: Configuracao) -> Banco:
    banco.gravar_regras(config_offline.regras)
    ingerir(criar_cliente(config_offline), banco, config_offline.regras, hoje=HOJE)
    return banco


def por_nome(situacoes, nome):
    return next(s for s in situacoes if s.instituicao == nome)


# ---------------------------------------------------------------------------
# Detecção
# ---------------------------------------------------------------------------


def test_avalia_todas_as_instituicoes_conectadas(banco_com_dados: Banco) -> None:
    situacoes = verificar_frescor(banco_com_dados, hoje=HOJE)

    assert {s.instituicao for s in situacoes} == {
        "PicPay", "Santander", "Nubank", "Inter", "Rico Investimentos"
    }


def test_instituicao_parada_e_apontada(banco_com_dados: Banco) -> None:
    picpay = por_nome(verificar_frescor(banco_com_dados, hoje=HOJE), "PicPay")

    assert picpay.ultima_transacao == date(2025, 8, 6)
    assert picpay.dias_de_atraso == 45
    assert picpay.fresca is False


def test_instituicao_em_dia_passa(banco_com_dados: Banco) -> None:
    santander = por_nome(verificar_frescor(banco_com_dados, hoje=HOJE), "Santander")

    assert santander.ultima_transacao == date(2025, 9, 15)
    assert santander.dias_de_atraso == 5
    assert santander.fresca is True


def test_atrasadas_sao_exatamente_as_que_estouraram_o_limite(
    banco_com_dados: Banco,
) -> None:
    """Em 2025-09-20, contra a última transação de cada instituição:

        Inter        14/09   6d  > 5   ATRASADA
        Nubank       10/09  10d  > 5   ATRASADA
        PicPay       06/08  45d  > 5   ATRASADA
        Santander    15/09   5d  = 5   ok
        Rico         16/09   4d  < 10  ok  (limite próprio)
    """
    velhas = atrasadas(verificar_frescor(banco_com_dados, hoje=HOJE))

    assert [s.instituicao for s in velhas] == ["Inter", "Nubank", "PicPay"]


# ---------------------------------------------------------------------------
# Tolerância configurável
# ---------------------------------------------------------------------------


def test_limite_especifico_vence_o_padrao(banco_com_dados: Banco) -> None:
    """O `regras.toml` dá 10 dias à Rico, contra os 5 do padrão."""
    situacoes = verificar_frescor(banco_com_dados, hoje=HOJE)

    assert por_nome(situacoes, "Rico Investimentos").dias_maximos == 10
    assert por_nome(situacoes, "Nubank").dias_maximos == 5


def test_padrao_like_casa_o_nome_completo_do_conector(banco_com_dados: Banco) -> None:
    """A regra escreve `rico%`; o conector devolve "Rico Investimentos". Um
    JOIN por igualdade falharia em silêncio, deixando a Rico no padrão."""
    rico = por_nome(verificar_frescor(banco_com_dados, hoje=HOJE), "Rico Investimentos")

    assert rico.dias_maximos == 10
    assert rico.ultima_transacao == date(2025, 9, 16)
    assert rico.fresca is True


def test_tolerancia_absorve_a_latencia_de_24h(banco_com_dados: Banco) -> None:
    """Armadilha 5: 'hoje' nunca está completo, então 1 dia sem movimento é
    normal e não pode virar alerta."""
    santander = por_nome(
        verificar_frescor(banco_com_dados, hoje=date(2025, 9, 16)), "Santander"
    )

    assert santander.dias_de_atraso == 1
    assert santander.fresca is True


def test_estouro_do_limite_muda_o_veredito(banco_com_dados: Banco) -> None:
    """Mesmo dado, dois dias de referência: o que muda é só a passagem do tempo."""
    no_limite = por_nome(
        verificar_frescor(banco_com_dados, hoje=date(2025, 9, 20)), "Santander"
    )
    um_dia_depois = por_nome(
        verificar_frescor(banco_com_dados, hoje=date(2025, 9, 21)), "Santander"
    )

    assert (no_limite.dias_de_atraso, no_limite.fresca) == (5, True)
    assert (um_dia_depois.dias_de_atraso, um_dia_depois.fresca) == (6, False)


# ---------------------------------------------------------------------------
# Casos de borda
# ---------------------------------------------------------------------------


def test_banco_vazio_devolve_lista_vazia(banco: Banco) -> None:
    """Distinto de 'tudo fresco': quem chama precisa saber que não há o que
    avaliar, senão a CLI diria 'ok' com o banco zerado."""
    assert verificar_frescor(banco, hoje=HOJE) == []


def test_conta_sem_nenhuma_transacao_nunca_e_fresca(
    banco: Banco, config_offline: Configuracao
) -> None:
    """Conexão que existe mas nunca trouxe nada é o caso mais suspeito, e um
    INNER JOIN a esconderia."""
    banco.gravar_regras(config_offline.regras)
    banco.gravar_contas(
        [
            {
                "id": "conta-fantasma",
                "data_posicao": HOJE,
                "instituicao": "Banco Mudo",
                "payload_json": "{}",
            }
        ]
    )

    (situacao,) = verificar_frescor(banco, hoje=HOJE)

    assert situacao.ultima_transacao is None
    assert situacao.dias_de_atraso is None
    assert situacao.fresca is False
    assert "nenhuma transação" in situacao.descrever()


def test_instituicao_que_saiu_do_ultimo_retrato_e_ignorada(
    banco_com_dados: Banco, config_offline: Configuracao
) -> None:
    """Banco desconectado não pode gerar alerta para sempre. A avaliação usa só
    o retrato de contas mais recente."""
    ingerir(
        criar_cliente(config_offline),
        banco_com_dados,
        config_offline.regras,
        hoje=date(2025, 9, 21),
    )
    banco_com_dados.conexao.execute(
        "DELETE FROM raw_contas "
        "WHERE data_posicao = DATE '2025-09-21' AND instituicao = 'PicPay'"
    )

    situacoes = verificar_frescor(banco_com_dados, hoje=date(2025, 9, 21))

    assert "PicPay" not in {s.instituicao for s in situacoes}


def test_descricao_e_legivel(banco_com_dados: Banco) -> None:
    picpay = por_nome(verificar_frescor(banco_com_dados, hoje=HOJE), "PicPay")

    assert picpay.descrever() == (
        "PicPay: última em 2025-08-06 (45d atrás, tolerância 5d) [ATRASADA]"
    )
