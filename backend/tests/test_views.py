"""
Testes das views SQL — a parte do projeto que responde às perguntas.

As fixtures foram montadas para que cada armadilha tenha um caso concreto:

    tx-nu-b-01  Nubank      Pagamento de fatura        -1200,00   armadilha 1
    tx-sa-b-01  Santander   PAGTO CARTAO SANTANDER      -890,30   armadilha 1
    tx-in-b-02  Inter       Pagamento Fatura Cartao     -410,00   armadilha 1
    tx-nu-c-04  Nubank      Pagamento recebido         +1200,00   armadilha 1 (lado do cartão)
    tx-nu-b-02  Nubank      Pix p/ CPF próprio          -500,00   armadilha 2
    tx-sa-b-02  Santander   Pix p/ telefone próprio     -300,00   armadilha 2
    tx-sa-b-03  Santander   TED p/ corretora própria   -2000,00   armadilha 2
    tx-ri-b-02  Rico        Aplicacao CDB Rico         -2000,00   armadilha 3

Somados, R$ 5.100,30 de débito que **não** são gasto. Sem os filtros, o total do
período seria mais de quatro vezes o real.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from financas.config import Configuracao
from financas.ingestao import ingerir
from financas.persistencia import Banco
from financas.pluggy import criar_cliente
from financas.views import aplicar_views, listar_arquivos

from conftest import RAIZ

SQL = RAIZ / "sql"


def uma(banco: Banco, consulta: str):
    return banco.conexao.execute(consulta).fetchone()


def ids(banco: Banco, consulta: str) -> set[str]:
    return {linha[0] for linha in banco.conexao.execute(consulta).fetchall()}


# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------


def test_as_seis_views_do_repositorio_sao_aplicadas(banco_com_views: Banco) -> None:
    existentes = ids(
        banco_com_views,
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_type = 'VIEW' AND table_schema = 'main'",
    )

    assert {
        "stg_transacoes",
        "stg_contas",
        "stg_investimentos",
        "gastos",
        "recorrencias",
        "patrimonio",
    } <= existentes


def test_staging_vem_antes_de_marts(banco_com_views: Banco) -> None:
    camadas = [camada for camada, _ in listar_arquivos(SQL)]

    assert camadas == ["staging"] * 3 + ["marts"] * 3


def test_reaplicar_views_e_idempotente(banco_com_views: Banco) -> None:
    antes = uma(banco_com_views, "SELECT count(*), sum(valor) FROM gastos")

    aplicar_views(banco_com_views, SQL)

    assert uma(banco_com_views, "SELECT count(*), sum(valor) FROM gastos") == antes


# ---------------------------------------------------------------------------
# Armadilha 1: dupla contagem de cartão
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "id_transacao", ["tx-nu-b-01", "tx-sa-b-01", "tx-in-b-02", "tx-nu-c-04"]
)
def test_pagamento_de_fatura_e_marcado(banco_com_views: Banco, id_transacao: str) -> None:
    """Três instituições, três redações diferentes, todas reconhecidas."""
    (marcado,) = uma(
        banco_com_views,
        f"SELECT e_pagamento_de_fatura FROM stg_transacoes "
        f"WHERE id_transacao = '{id_transacao}'",
    )

    assert marcado is True


def test_pagamento_de_fatura_nao_entra_em_gastos(banco_com_views: Banco) -> None:
    presentes = ids(banco_com_views, "SELECT id_transacao FROM gastos")

    assert not presentes & {"tx-nu-b-01", "tx-sa-b-01", "tx-in-b-02"}


def test_a_compra_no_cartao_continua_contando(banco_com_views: Banco) -> None:
    """O filtro tira o pagamento da fatura, não as compras que a formaram."""
    presentes = ids(banco_com_views, "SELECT id_transacao FROM gastos")

    assert {"tx-nu-c-01", "tx-nu-c-02", "tx-nu-c-03"} <= presentes


def test_sem_o_filtro_o_gasto_dobraria(banco_com_views: Banco) -> None:
    """O tamanho do erro que a armadilha 1 causaria, em números."""
    (dupla_contagem,) = uma(
        banco_com_views,
        "SELECT -sum(valor) FROM stg_transacoes "
        "WHERE e_pagamento_de_fatura AND valor < 0",
    )

    assert dupla_contagem == Decimal("2500.30")


# ---------------------------------------------------------------------------
# Armadilha 2: transferência entre contas próprias
# ---------------------------------------------------------------------------


def test_pix_para_cpf_proprio_e_marcado(banco_com_views: Banco) -> None:
    (marcado,) = uma(
        banco_com_views,
        "SELECT e_transferencia_propria FROM stg_transacoes "
        "WHERE id_transacao = 'tx-nu-b-02'",
    )

    assert marcado is True


def test_pix_para_telefone_proprio_e_marcado(banco_com_views: Banco) -> None:
    """A chave está só no meio da descrição, não num campo estruturado."""
    (marcado,) = uma(
        banco_com_views,
        "SELECT e_transferencia_propria FROM stg_transacoes "
        "WHERE id_transacao = 'tx-sa-b-02'",
    )

    assert marcado is True


def test_ted_para_conta_propria_e_pega_pelo_nome_do_titular(
    banco_com_views: Banco,
) -> None:
    """TED não traz chave Pix nenhuma: sobra o nome do titular."""
    (marcado,) = uma(
        banco_com_views,
        "SELECT e_transferencia_propria FROM stg_transacoes "
        "WHERE id_transacao = 'tx-sa-b-03'",
    )

    assert marcado is True


def test_transferencia_propria_nao_entra_em_gastos(banco_com_views: Banco) -> None:
    presentes = ids(banco_com_views, "SELECT id_transacao FROM gastos")

    assert not presentes & {"tx-nu-b-02", "tx-sa-b-02", "tx-sa-b-03"}


def test_compra_comum_nao_e_confundida_com_transferencia(
    banco_com_views: Banco,
) -> None:
    """Guarda contra filtro largo demais: mercado e posto são gasto de verdade."""
    marcados = ids(
        banco_com_views,
        "SELECT id_transacao FROM stg_transacoes WHERE e_transferencia_propria",
    )

    assert not marcados & {"tx-nu-b-04", "tx-sa-b-04", "tx-pp-b-02"}


# ---------------------------------------------------------------------------
# Armadilha 3: aporte não é despesa
# ---------------------------------------------------------------------------


def test_aplicacao_em_cdb_e_marcada(banco_com_views: Banco) -> None:
    """Sai da conta corrente como débito, mas o dinheiro continua sendo seu."""
    (marcado,) = uma(
        banco_com_views,
        "SELECT e_aplicacao FROM stg_transacoes WHERE id_transacao = 'tx-ri-b-02'",
    )

    assert marcado is True


def test_aplicacao_nao_entra_em_gastos(banco_com_views: Banco) -> None:
    assert "tx-ri-b-02" not in ids(banco_com_views, "SELECT id_transacao FROM gastos")


def test_investimento_nunca_encosta_em_gastos(banco_com_views: Banco) -> None:
    """As duas metades do projeto não se cruzam: gastos vem de transação,
    patrimônio vem de posição."""
    de_gastos = ids(banco_com_views, "SELECT id_transacao FROM gastos")
    de_investimentos = ids(
        banco_com_views, "SELECT id_investimento FROM stg_investimentos"
    )

    assert not de_gastos & de_investimentos


# ---------------------------------------------------------------------------
# gastos: o contrato
# ---------------------------------------------------------------------------


def test_total_de_gastos_do_periodo(banco_com_views: Banco) -> None:
    quantas, total = uma(banco_com_views, "SELECT count(*), sum(valor) FROM gastos")

    assert (quantas, total) == (15, Decimal("1434.75"))


def test_valor_de_gasto_e_positivo(banco_com_views: Banco) -> None:
    """Na raw um gasto é negativo, porque é assim que a API manda. Somar
    despesa negativa é fonte constante de erro de sinal em relatório."""
    (negativos,) = uma(banco_com_views, "SELECT count(*) FROM gastos WHERE valor <= 0")

    assert negativos == 0


def test_receita_nao_entra_em_gastos(banco_com_views: Banco) -> None:
    assert "tx-nu-b-03" not in ids(  # salário
        banco_com_views, "SELECT id_transacao FROM gastos"
    )


def test_gastos_tem_ano_e_mes_separados(banco_com_views: Banco) -> None:
    """EXTRACT em vez de date_trunc: a assinatura de date_trunc muda no
    BigQuery, e a migração está no radar."""
    por_mes = banco_com_views.conexao.execute(
        "SELECT ano, mes, count(*), sum(valor) FROM gastos GROUP BY 1, 2 ORDER BY 1, 2"
    ).fetchall()

    assert por_mes == [
        (2025, 8, 5, Decimal("329.20")),
        (2025, 9, 10, Decimal("1105.55")),
    ]


def test_tipo_de_conta_vem_do_retrato_atual(banco_com_views: Banco) -> None:
    """O join com stg_contas não pode multiplicar linhas: raw_contas tem um
    retrato por dia."""
    (tipo,) = uma(
        banco_com_views,
        "SELECT tipo_de_conta FROM gastos WHERE id_transacao = 'tx-nu-c-01'",
    )

    assert tipo == "CREDIT"


def test_join_com_contas_nao_duplica_gasto(
    banco: Banco, config_offline: Configuracao
) -> None:
    """Com dois retratos de conta no banco, o total de gastos não pode dobrar."""
    banco.gravar_regras(config_offline.regras)
    cliente = criar_cliente(config_offline)
    ingerir(cliente, banco, config_offline.regras, hoje=date(2025, 9, 20))
    ingerir(cliente, banco, config_offline.regras, hoje=date(2025, 9, 21))
    aplicar_views(banco, SQL)

    assert banco.contar("raw_contas") == 16
    assert uma(banco, "SELECT count(*) FROM gastos") == (15,)


def test_parcelamento_e_sinalizado(banco_com_views: Banco) -> None:
    parcelado, numero, total = uma(
        banco_com_views,
        "SELECT e_parcelado, parcela_numero, parcela_total FROM gastos "
        "WHERE id_transacao = 'tx-nu-c-03'",
    )

    assert (parcelado, numero, total) == (True, 1, 3)


# ---------------------------------------------------------------------------
# recorrencias
# ---------------------------------------------------------------------------


def test_assinaturas_sao_detectadas(banco_com_views: Banco) -> None:
    encontradas = banco_com_views.conexao.execute(
        "SELECT estabelecimento, meses_observados, valor_medio, custo_anual_estimado "
        "FROM recorrencias ORDER BY estabelecimento"
    ).fetchall()

    assert encontradas == [
        ("Netflix", 2, 55.90, pytest.approx(670.80)),
        ("Smart Fit", 2, 99.90, pytest.approx(1198.80)),
        ("Spotify", 2, 21.90, pytest.approx(262.80)),
    ]


def test_gasto_variavel_no_mesmo_lugar_nao_vira_assinatura(
    banco_com_views: Banco,
) -> None:
    """O mercado aparece em agosto (R$ 89,20) e setembro (R$ 320,55). Repetição
    não basta: o valor precisa ser estável."""
    assert "Supermercado Big" not in ids(
        banco_com_views, "SELECT estabelecimento FROM recorrencias"
    )


def test_compra_avulsa_nao_vira_assinatura(banco_com_views: Banco) -> None:
    encontradas = ids(banco_com_views, "SELECT estabelecimento FROM recorrencias")

    assert "Uber *Trip" not in encontradas
    assert "Posto Ipiranga" not in encontradas


def test_limiar_de_meses_vem_da_configuracao(
    banco_com_views: Banco, config_offline: Configuracao
) -> None:
    """Calibrar a detecção é editar o regras.toml, não o .sql."""
    from dataclasses import replace

    banco_com_views.gravar_regras(
        replace(config_offline.regras, recorrencia_meses_minimos=3)
    )
    aplicar_views(banco_com_views, SQL)

    # Com o histórico de 2 meses das fixtures, exigir 3 esvazia a view.
    assert uma(banco_com_views, "SELECT count(*) FROM recorrencias") == (0,)


def test_limiar_de_variacao_vem_da_configuracao(
    banco_com_views: Banco, config_offline: Configuracao
) -> None:
    from dataclasses import replace

    banco_com_views.gravar_regras(
        replace(config_offline.regras, recorrencia_variacao_maxima=1.5)
    )
    aplicar_views(banco_com_views, SQL)

    # Afrouxando a variação, o mercado passa a ser considerado recorrente.
    assert "Supermercado Big" in ids(
        banco_com_views, "SELECT estabelecimento FROM recorrencias"
    )


# ---------------------------------------------------------------------------
# patrimonio
# ---------------------------------------------------------------------------


def test_patrimonio_tem_uma_linha_por_instituicao_por_dia(
    banco_com_views: Banco,
) -> None:
    """Contas e investimentos precisam usar o mesmo calendário, senão a Rico
    aparece duas vezes: uma com conta e outra com investimento."""
    linhas = banco_com_views.conexao.execute(
        "SELECT data_posicao, instituicao FROM patrimonio"
    ).fetchall()

    assert len(linhas) == len(set(linhas)) == 5


def test_investimento_soma_no_patrimonio_da_rico(banco_com_views: Banco) -> None:
    saldo, investido, fatura, liquido = uma(
        banco_com_views,
        "SELECT saldo_em_conta, investido, fatura_em_aberto, patrimonio_liquido "
        "FROM patrimonio WHERE instituicao = 'Rico Investimentos'",
    )

    assert saldo == Decimal("105.00")
    assert investido == Decimal("7192.79")  # CDB 2012,35 + Tesouro 5180,44
    assert fatura == Decimal("120.00")
    assert liquido == Decimal("7177.79")


def test_fatura_em_aberto_desconta_do_patrimonio(banco_com_views: Banco) -> None:
    saldo, fatura, liquido = uma(
        banco_com_views,
        "SELECT saldo_em_conta, fatura_em_aberto, patrimonio_liquido "
        "FROM patrimonio WHERE instituicao = 'Nubank'",
    )

    assert (saldo, fatura, liquido) == (
        Decimal("4812.44"),
        Decimal("1196.80"),
        Decimal("3615.64"),
    )


def test_instituicao_sem_investimento_nao_some(banco_com_views: Banco) -> None:
    """FULL OUTER JOIN: só a Rico tem investimento, e as outras quatro
    continuam na série."""
    presentes = ids(banco_com_views, "SELECT instituicao FROM patrimonio")

    assert presentes == {
        "PicPay", "Santander", "Nubank", "Inter", "Rico Investimentos"
    }


def test_patrimonio_vira_serie_com_mais_de_uma_ingestao(
    banco: Banco, config_offline: Configuracao
) -> None:
    """O motivo de a chave natural de conta carregar a data."""
    banco.gravar_regras(config_offline.regras)
    cliente = criar_cliente(config_offline)
    ingerir(cliente, banco, config_offline.regras, hoje=date(2025, 9, 20))
    ingerir(cliente, banco, config_offline.regras, hoje=date(2025, 9, 21))
    aplicar_views(banco, SQL)

    serie = banco.conexao.execute(
        "SELECT data_posicao, sum(patrimonio_liquido) FROM patrimonio "
        "GROUP BY 1 ORDER BY 1"
    ).fetchall()

    assert [linha[0] for linha in serie] == [date(2025, 9, 20), date(2025, 9, 21)]
    assert serie[0][1] == serie[1][1]  # nada mudou entre os dois dias
