"""
Testes do achatamento do JSON da Pluggy.

Dois pontos concentram o risco: perder campo aninhado (e com ele a capacidade de
identificar transferência própria) e estragar dinheiro convertendo para float.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from financas.normalizacao import (
    INSTITUICAO_DESCONHECIDA,
    nome_da_instituicao,
    normalizar_conta,
    normalizar_investimento,
    normalizar_transacao,
    serializar,
)


def normalizar(bruto: dict) -> dict:
    return normalizar_transacao(bruto, id_item="item-1", instituicao="Nubank")


# ---------------------------------------------------------------------------
# Transações
# ---------------------------------------------------------------------------


def test_campos_simples_viram_colunas() -> None:
    linha = normalizar(
        {
            "id": "tx-1",
            "accountId": "conta-1",
            "description": "Supermercado Big",
            "descriptionRaw": "SUPERMERCADO BIG LTDA",
            "amount": -320.55,
            "currencyCode": "BRL",
            "date": "2025-09-03T00:00:00.000Z",
            "type": "DEBIT",
            "status": "POSTED",
        }
    )

    assert linha["id"] == "tx-1"
    assert linha["id_conta"] == "conta-1"
    assert linha["descricao"] == "Supermercado Big"
    assert linha["data"] == date(2025, 9, 3)
    assert linha["tipo"] == "DEBIT"


def test_procedencia_e_propagada_da_travessia() -> None:
    """A API não devolve instituição junto da transação; sem propagar, a
    armadilha 1 não teria como aplicar padrão por instituição."""
    linha = normalizar({"id": "tx-1"})

    assert linha["id_item"] == "item-1"
    assert linha["instituicao"] == "Nubank"


def test_contraparte_aninhada_e_extraida() -> None:
    """Armadilha 2: sem estes campos não dá para reconhecer conta própria."""
    linha = normalizar(
        {
            "id": "tx-1",
            "paymentData": {
                "paymentMethod": "PIX",
                "payer": {
                    "name": "FULANO DE TAL",
                    "documentNumber": {"type": "CPF", "value": "12345678909"},
                },
                "receiver": {
                    "name": "FULANO DE TAL",
                    "documentNumber": {"type": "CPF", "value": "12345678909"},
                    "pixKey": "123.456.789-09",
                },
            },
        }
    )

    assert linha["metodo_pagamento"] == "PIX"
    assert linha["pagador_documento"] == "12345678909"
    assert linha["recebedor_nome"] == "FULANO DE TAL"
    assert linha["recebedor_chave_pix"] == "123.456.789-09"


def test_dados_de_cartao_sao_extraidos() -> None:
    linha = normalizar(
        {
            "id": "tx-1",
            "creditCardMetadata": {
                "cardNumber": "4321",
                "installmentNumber": 1,
                "totalInstallments": 3,
            },
        }
    )

    assert linha["cartao_final"] == "4321"
    assert linha["parcela_numero"] == 1
    assert linha["parcela_total"] == 3


def test_caminho_aninhado_ausente_vira_nulo_sem_estourar() -> None:
    linha = normalizar({"id": "tx-1"})

    assert linha["recebedor_chave_pix"] is None
    assert linha["pagador_nome"] is None
    assert linha["estabelecimento_cnpj"] is None


def test_caminho_aninhado_incompleto_tambem_vira_nulo() -> None:
    linha = normalizar({"id": "tx-1", "paymentData": {"receiver": None}})

    assert linha["recebedor_nome"] is None


# ---------------------------------------------------------------------------
# Conversões
# ---------------------------------------------------------------------------


def test_dinheiro_vira_decimal_e_nao_float() -> None:
    linha = normalizar({"id": "tx-1", "amount": -320.55})

    assert isinstance(linha["valor"], Decimal)
    assert linha["valor"] == Decimal("-320.55")


def test_soma_de_decimais_e_exata() -> None:
    """O motivo de existir Decimal aqui: 0.1 + 0.2 em float não dá 0.3."""
    valores = [normalizar({"id": f"tx-{i}", "amount": v})["valor"] for i, v in
               enumerate([0.1, 0.2])]

    assert sum(valores) == Decimal("0.30")


def test_data_iso_com_hora_e_fuso_vira_date() -> None:
    linha = normalizar({"id": "tx-1", "date": "2025-09-10T23:59:59.999Z"})

    assert linha["data"] == date(2025, 9, 10)


@pytest.mark.parametrize("valor", ["", "   ", None])
def test_texto_vazio_vira_nulo(valor: object) -> None:
    linha = normalizar({"id": "tx-1", "description": valor})

    assert linha["descricao"] is None


@pytest.mark.parametrize("valor", ["nao-e-data", "2025", None, 42])
def test_data_invalida_vira_nulo(valor: object) -> None:
    assert normalizar({"id": "tx-1", "date": valor})["data"] is None


def test_valor_invalido_vira_nulo_em_vez_de_estourar() -> None:
    assert normalizar({"id": "tx-1", "amount": "muito dinheiro"})["valor"] is None


# ---------------------------------------------------------------------------
# payload_json
# ---------------------------------------------------------------------------


def test_payload_guarda_o_json_original_inteiro() -> None:
    bruto = {"id": "tx-1", "campoQueNinguemPreviu": {"aninhado": True}}

    payload = normalizar(bruto)["payload_json"]

    assert "campoQueNinguemPreviu" in payload


def test_payload_independe_da_ordem_das_chaves() -> None:
    """Sem isso, a mesma transação com as chaves em outra ordem pareceria
    alterada e o upsert marcaria uma atualização que não existiu."""
    assert serializar({"a": 1, "b": 2}) == serializar({"b": 2, "a": 1})


def test_payload_preserva_acento_sem_escapar() -> None:
    assert "Salário" in serializar({"description": "Salário"})


# ---------------------------------------------------------------------------
# Contas
# ---------------------------------------------------------------------------


def test_conta_carrega_a_data_da_posicao() -> None:
    """Conta é estado, não evento: a data é parte da chave."""
    linha = normalizar_conta(
        {"id": "conta-1", "type": "BANK", "balance": 4812.44},
        id_item="item-1",
        instituicao="Nubank",
        data_posicao=date(2025, 9, 20),
    )

    assert linha["data_posicao"] == date(2025, 9, 20)
    assert linha["saldo"] == Decimal("4812.44")


def test_dados_de_cartao_da_conta_sao_extraidos() -> None:
    linha = normalizar_conta(
        {
            "id": "conta-2",
            "type": "CREDIT",
            "creditData": {
                "creditLimit": 10000.00,
                "availableCreditLimit": 8803.20,
                "balanceCloseDate": "2025-09-25",
                "balanceDueDate": "2025-10-05",
            },
        },
        id_item="item-1",
        instituicao="Nubank",
        data_posicao=date(2025, 9, 20),
    )

    assert linha["limite_credito"] == Decimal("10000.00")
    assert linha["vencimento_fatura"] == date(2025, 10, 5)


# ---------------------------------------------------------------------------
# Investimentos
# ---------------------------------------------------------------------------


def test_investimento_usa_a_data_da_ingestao_como_posicao() -> None:
    """A data da corretora fica em `data_referencia`, não na chave.

    Se cada tabela usasse um calendário diferente, `patrimonio` não conseguiria
    somar saldo de conta com posição de investimento no mesmo dia.
    """
    linha = normalizar_investimento(
        {"id": "inv-1", "date": "2025-09-30T00:00:00.000Z"},
        id_item="item-rico",
        instituicao="Rico",
        data_posicao=date(2025, 10, 2),
    )

    assert linha["data_posicao"] == date(2025, 10, 2)
    assert linha["data_referencia"] == date(2025, 9, 30)


def test_investimento_sem_data_da_corretora_fica_com_referencia_nula() -> None:
    linha = normalizar_investimento(
        {"id": "inv-1"},
        id_item="item-rico",
        instituicao="Rico",
        data_posicao=date(2025, 10, 2),
    )

    assert linha["data_posicao"] == date(2025, 10, 2)
    assert linha["data_referencia"] is None


def test_quantidade_de_cotas_aceita_fracao() -> None:
    linha = normalizar_investimento(
        {"id": "inv-1", "quantity": 32.5},
        id_item="item-rico",
        instituicao="Rico",
        data_posicao=date(2025, 9, 30),
    )

    assert linha["quantidade"] == Decimal("32.50000000")


def test_valor_aplicado_prefere_o_original() -> None:
    linha = normalizar_investimento(
        {"id": "inv-1", "amount": 2500.00, "amountOriginal": 2000.00},
        id_item="item-rico",
        instituicao="Rico",
        data_posicao=date(2025, 9, 30),
    )

    assert linha["valor_aplicado"] == Decimal("2000.00")


# ---------------------------------------------------------------------------
# Instituição
# ---------------------------------------------------------------------------


def test_nome_da_instituicao_vem_do_conector() -> None:
    assert nome_da_instituicao({"connector": {"name": "Nubank"}}) == "Nubank"


@pytest.mark.parametrize(
    "item", [{}, {"connector": None}, {"connector": {}}, {"connector": {"name": "  "}}]
)
def test_instituicao_ausente_tem_valor_de_reserva(item: dict) -> None:
    """Preferível a `None`: instituição é usada em filtro, e nulo silencioso
    faria a transação sumir do relatório sem ninguém perceber."""
    assert nome_da_instituicao(item) == INSTITUICAO_DESCONHECIDA
