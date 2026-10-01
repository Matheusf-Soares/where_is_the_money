"""Achados da auditoria dos valores contra o dado real, transformados em invariantes.

Quatro modos de falha silenciosa, todos encontrados com dado de verdade:

1. "Saldo em atraso" e "Saldo em rotativo" são o saldo da fatura anterior
   lançado de novo na seguinte. As compras já foram contadas quando
   aconteceram; contar o saldo outra vez dobra o gasto daquele mês.
2. A API não manda valor aplicado nem rendimento de ações e FIIs. Inventar
   `saldo - saldo = 0` faz a tela afirmar um rendimento que ninguém informou.
3. A Pluggy reemite uma transação pendente com id NOVO quando ela é lançada, e
   a pendente antiga continua no banco. As duas contam.
4. Sincronização concluída não prova dado novo: a tela precisa do veredito de
   frescor, calculado em SQL com a mesma regra do comando `frescor`.

Tudo sintético, inserido direto nas tabelas raw sobre o banco das fixtures.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from financas.config import carregar_configuracao
from financas.frescor import verificar_frescor
from financas.persistencia import Banco

from conftest import FIXTURES_PLUGGY, REGRAS_MINIMAS


def uma(banco: Banco, consulta: str, *parametros):
    linhas = banco.conexao.execute(consulta, list(parametros)).fetchall()
    assert len(linhas) == 1, f"esperava 1 linha, vieram {len(linhas)}: {consulta}"
    return linhas[0]


def inserir_transacao(banco: Banco, id_: str, *, conta: str, instituicao: str, descricao: str,
                      valor: str, tipo: str, data: str, situacao: str = "POSTED") -> None:
    banco.conexao.execute(
        """
        INSERT INTO raw_transacoes (id, id_conta, id_item, instituicao, descricao, valor, moeda,
            data, tipo, situacao, payload_json, ingerido_em, atualizado_em)
        VALUES (?, ?, 'item-sintetico', ?, ?, CAST(? AS DECIMAL(18,2)), 'BRL', CAST(? AS DATE),
            ?, ?, '{}', now(), now())
        """,
        [id_, conta, instituicao, descricao, valor, data, tipo, situacao],
    )


# ---------------------------------------------------------------------------
# 1. Saldo da fatura anterior não é gasto novo
# ---------------------------------------------------------------------------


def test_regras_aceitam_padroes_de_saldo_anterior(projeto) -> None:
    (projeto / "config" / "regras.toml").write_text(
        REGRAS_MINIMAS + '\n[[saldo_anterior_fatura]]\ninstituicao = "nubank"\npadrao = "saldo em atraso%"\n',
        encoding="utf-8",
    )
    regras = carregar_configuracao(ambiente={"FINANCAS_FIXTURES": str(FIXTURES_PLUGGY)}, raiz=projeto).regras
    assert [(p.instituicao, p.padrao) for p in regras.padroes_saldo_anterior] == [("nubank", "saldo em atraso%")]


def test_saldo_anterior_e_gravado_em_cfg(banco: Banco, projeto) -> None:
    (projeto / "config" / "regras.toml").write_text(
        REGRAS_MINIMAS + '\n[[saldo_anterior_fatura]]\ninstituicao = "nubank"\npadrao = "saldo em rotativo%"\n',
        encoding="utf-8",
    )
    regras = carregar_configuracao(ambiente={"FINANCAS_FIXTURES": str(FIXTURES_PLUGGY)}, raiz=projeto).regras
    banco.gravar_regras(regras)
    assert banco.conexao.execute("SELECT instituicao, padrao FROM cfg_padroes_saldo_anterior").fetchall() == [
        ("nubank", "saldo em rotativo%")
    ]


def test_saldo_em_atraso_sai_do_gasto_e_juros_continuam(banco_com_views: Banco) -> None:
    banco_com_views.conexao.execute(
        "INSERT INTO cfg_padroes_saldo_anterior VALUES ('nubank%', 'saldo em atraso%', 'sintético')"
    )
    inserir_transacao(banco_com_views, "tx-saldo-atraso", conta="conta-nubank-credit", instituicao="Nubank",
                      descricao="Saldo em atraso", valor="1234.56", tipo="DEBIT", data="2025-09-14")
    inserir_transacao(banco_com_views, "tx-multa", conta="conta-nubank-credit", instituicao="Nubank",
                      descricao="Multa de atraso", valor="12.34", tipo="DEBIT", data="2025-09-14")

    (marcada,) = uma(banco_com_views, "SELECT e_saldo_anterior FROM stg_transacoes WHERE id_transacao = 'tx-saldo-atraso'")
    assert marcada is True
    gastos = {r[0] for r in banco_com_views.conexao.execute("SELECT id_transacao FROM gastos").fetchall()}
    assert "tx-saldo-atraso" not in gastos and "tx-multa" in gastos

    e_gasto, motivo = uma(banco_com_views,
        "SELECT e_gasto, motivo_exclusao FROM transacoes_analiticas WHERE id_transacao = 'tx-saldo-atraso'")
    assert (e_gasto, motivo) == (False, "saldo_de_fatura_anterior")
    (multa,) = uma(banco_com_views, "SELECT e_gasto FROM transacoes_analiticas WHERE id_transacao = 'tx-multa'")
    assert multa is True


def test_sem_padrao_configurado_nada_e_marcado_como_saldo_anterior(banco_com_views: Banco) -> None:
    inserir_transacao(banco_com_views, "tx-saldo-sem-regra", conta="conta-nubank-credit", instituicao="Nubank",
                      descricao="Saldo em atraso", valor="10.00", tipo="DEBIT", data="2025-09-14")
    (marcada,) = uma(banco_com_views, "SELECT e_saldo_anterior FROM stg_transacoes WHERE id_transacao = 'tx-saldo-sem-regra'")
    assert marcada is False


# ---------------------------------------------------------------------------
# 2. Rendimento não informado continua não informado
# ---------------------------------------------------------------------------


def inserir_investimento(banco: Banco, id_: str, payload: str, *, saldo: str, aplicado: str | None,
                         rendimento: str | None) -> None:
    banco.conexao.execute(
        """
        INSERT INTO raw_investimentos (id, data_posicao, id_item, instituicao, nome, tipo, moeda,
            valor_aplicado, saldo, rendimento, payload_json, ingerido_em, atualizado_em)
        VALUES (?, DATE '2025-09-20', 'item-sintetico', 'Rico', ?, 'EQUITY', 'BRL',
            CAST(? AS DECIMAL(18,2)), CAST(? AS DECIMAL(18,2)), CAST(? AS DECIMAL(18,2)), ?, now(), now())
        """,
        [id_, id_, aplicado, saldo, rendimento, payload],
    )


def test_acao_sem_valor_aplicado_nao_ganha_rendimento_zero(banco_com_views: Banco) -> None:
    # Antes da correção a normalização copiava `amount` para valor_aplicado.
    inserir_investimento(banco_com_views, "inv-acao", '{"amount": 500.00, "balance": 500.00}',
                         saldo="500.00", aplicado="500.00", rendimento=None)
    aplicado, rendimento = uma(banco_com_views,
        "SELECT valor_aplicado, rendimento FROM stg_investimentos WHERE id_investimento = 'inv-acao'")
    assert (aplicado, rendimento) == (None, None)


def test_renda_fixa_com_valor_original_calcula_rendimento(banco_com_views: Banco) -> None:
    inserir_investimento(banco_com_views, "inv-cdb", '{"amountOriginal": 1000, "balance": 1100.50}',
                         saldo="1100.50", aplicado="1000", rendimento=None)
    aplicado, rendimento = uma(banco_com_views,
        "SELECT valor_aplicado, rendimento FROM stg_investimentos WHERE id_investimento = 'inv-cdb'")
    assert (aplicado, rendimento) == (Decimal("1000.00"), Decimal("100.50"))


def test_rendimento_informado_pela_fonte_vence(banco_com_views: Banco) -> None:
    inserir_investimento(banco_com_views, "inv-fundo", '{"amountOriginal": 1000, "amountProfit": 42, "balance": 1100}',
                         saldo="1100", aplicado="1000", rendimento="42")
    (rendimento,) = uma(banco_com_views, "SELECT rendimento FROM stg_investimentos WHERE id_investimento = 'inv-fundo'")
    assert rendimento == Decimal("42.00")


def test_normalizacao_nao_usa_amount_como_valor_aplicado() -> None:
    from financas.normalizacao import normalizar_investimento

    linha = normalizar_investimento(
        {"id": "inv-2", "amount": 2500.00, "balance": 2500.00, "type": "EQUITY", "currencyCode": "BRL"},
        id_item="item", instituicao="Rico", data_posicao=date(2025, 9, 20),
    )
    assert linha["valor_aplicado"] is None


# ---------------------------------------------------------------------------
# 3. Pendente reemitida com id novo
# ---------------------------------------------------------------------------


def test_pendente_com_gemeo_lancado_e_marcada_e_sai_do_gasto(banco_com_views: Banco) -> None:
    inserir_transacao(banco_com_views, "tx-pendente", conta="conta-nubank-credit", instituicao="Nubank",
                      descricao="Padaria Exemplo", valor="18.90", tipo="DEBIT", data="2025-09-10", situacao="PENDING")
    inserir_transacao(banco_com_views, "tx-lancada", conta="conta-nubank-credit", instituicao="Nubank",
                      descricao="Padaria Exemplo", valor="18.90", tipo="DEBIT", data="2025-09-11")

    (marcada,) = uma(banco_com_views, "SELECT e_pendente_substituida FROM stg_transacoes WHERE id_transacao = 'tx-pendente'")
    assert marcada is True
    (lancada,) = uma(banco_com_views, "SELECT e_pendente_substituida FROM stg_transacoes WHERE id_transacao = 'tx-lancada'")
    assert lancada is False
    gastos = {r[0] for r in banco_com_views.conexao.execute("SELECT id_transacao FROM gastos").fetchall()}
    assert "tx-pendente" not in gastos and "tx-lancada" in gastos
    (motivo,) = uma(banco_com_views, "SELECT motivo_exclusao FROM transacoes_analiticas WHERE id_transacao = 'tx-pendente'")
    assert motivo == "pendente_substituida"


def test_duas_compras_de_mesmo_valor_em_lugares_diferentes_continuam(banco_com_views: Banco) -> None:
    """Dois abastecimentos de R$ 60 em postos diferentes são dois gastos reais."""
    inserir_transacao(banco_com_views, "tx-posto-a", conta="conta-nubank-credit", instituicao="Nubank",
                      descricao="Posto Alfa", valor="60.00", tipo="DEBIT", data="2025-09-12", situacao="PENDING")
    inserir_transacao(banco_com_views, "tx-posto-b", conta="conta-nubank-credit", instituicao="Nubank",
                      descricao="Posto Beta", valor="60.00", tipo="DEBIT", data="2025-09-10")
    (marcada,) = uma(banco_com_views, "SELECT e_pendente_substituida FROM stg_transacoes WHERE id_transacao = 'tx-posto-a'")
    assert marcada is False


def test_pagamento_pendente_reemitido_com_outra_descricao_e_marcado(banco_com_views: Banco) -> None:
    """A Pluggy troca o texto ao lançar o pagamento ("PAGAMENTO ON LINE" vira "Pagamento recebido")."""
    inserir_transacao(banco_com_views, "tx-pag-pendente", conta="conta-nubank-credit", instituicao="Nubank",
                      descricao="pagamento de fatura on line", valor="500.00", tipo="CREDIT", data="2025-09-11",
                      situacao="PENDING")
    inserir_transacao(banco_com_views, "tx-pag-lancado", conta="conta-nubank-credit", instituicao="Nubank",
                      descricao="Pagamento recebido", valor="500.00", tipo="CREDIT", data="2025-09-10")
    (marcada,) = uma(banco_com_views,
        "SELECT e_pendente_substituida FROM stg_transacoes WHERE id_transacao = 'tx-pag-pendente'")
    assert marcada is True


def test_parcela_futura_pendente_nao_e_tratada_como_substituida(banco_com_views: Banco) -> None:
    futura = (date.today() + timedelta(days=40)).isoformat()
    inserir_transacao(banco_com_views, "tx-futura-1", conta="conta-nubank-credit", instituicao="Nubank",
                      descricao="Loja Parcelada", valor="99.00", tipo="DEBIT", data=futura, situacao="PENDING")
    inserir_transacao(banco_com_views, "tx-futura-2", conta="conta-nubank-credit", instituicao="Nubank",
                      descricao="Loja Parcelada", valor="99.00", tipo="DEBIT", data=futura)
    (marcada,) = uma(banco_com_views, "SELECT e_pendente_substituida FROM stg_transacoes WHERE id_transacao = 'tx-futura-1'")
    assert marcada is False


# ---------------------------------------------------------------------------
# 4. Veredito de frescor publicado
# ---------------------------------------------------------------------------


def test_qualidade_publica_o_mesmo_veredito_do_comando_frescor(banco_com_views: Banco) -> None:
    situacoes = {s.instituicao: s for s in verificar_frescor(banco_com_views, hoje=date.today())}
    linhas = banco_com_views.conexao.execute(
        "SELECT instituicao, frescor_dias_maximos, dias_sem_transacao, e_desatualizada FROM qualidade_dados"
    ).fetchall()
    vistas = 0
    for instituicao, limite, dias, desatualizada in linhas:
        if instituicao not in situacoes:
            continue
        vistas += 1
        s = situacoes[instituicao]
        assert (limite, dias, desatualizada) == (s.dias_maximos, s.dias_de_atraso, not s.fresca), instituicao
    assert vistas >= 1


def test_limite_especifico_vence_o_padrao(banco_com_views: Banco) -> None:
    (limite,) = uma(banco_com_views, "SELECT frescor_dias_maximos FROM qualidade_dados WHERE lower(instituicao) LIKE 'rico%'")
    assert limite == 10
