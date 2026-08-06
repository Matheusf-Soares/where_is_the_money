"""
Testes da camada de persistência.

O teste que justifica o módulo inteiro é o de idempotência: gravar as mesmas
fixtures duas vezes, em instantes diferentes, tem que deixar o banco idêntico —
mesma contagem, mesmo conteúdo, mesmos timestamps.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from financas.config import Configuracao
from financas.normalizacao import serializar
from financas.persistencia import BANCO_EM_MEMORIA, Banco

from conftest import RelogioFalso


def linha_de_transacao(id_transacao: str = "tx-1", **campos: Any) -> dict[str, Any]:
    """Linha mínima de `raw_transacoes`, com o payload coerente com os campos."""
    base: dict[str, Any] = {
        "id": id_transacao,
        "id_conta": "conta-1",
        "id_item": "item-1",
        "instituicao": "Nubank",
        "descricao": "Supermercado Big",
        "valor": Decimal("-320.55"),
        "data": date(2025, 9, 3),
        "tipo": "DEBIT",
        "situacao": "POSTED",
    }
    base.update(campos)
    base["payload_json"] = serializar(
        {c: str(v) for c, v in base.items() if c != "payload_json"}
    )
    return base


def linha_de_conta(
    id_conta: str = "conta-1", data_posicao: date = date(2025, 9, 20), **campos: Any
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": id_conta,
        "data_posicao": data_posicao,
        "id_item": "item-1",
        "instituicao": "Nubank",
        "tipo": "BANK",
        "saldo": Decimal("4812.44"),
    }
    base.update(campos)
    base["payload_json"] = serializar(
        {c: str(v) for c, v in base.items() if c != "payload_json"}
    )
    return base


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_criar_schema_e_idempotente(banco: Banco) -> None:
    banco.criar_schema()  # a fixture já criou uma vez
    banco.criar_schema()

    assert banco.contar("raw_transacoes") == 0


def test_todas_as_tabelas_existem(banco: Banco) -> None:
    esperadas = {
        "raw_transacoes",
        "raw_contas",
        "raw_investimentos",
        "cfg_padroes_fatura",
        "cfg_contrapartes_proprias",
        "cfg_frescor",
        "cfg_geral",
    }

    existentes = {
        linha[0]
        for linha in banco.conexao.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }

    assert esperadas <= existentes


def test_gravar_sem_schema_diz_o_que_fazer() -> None:
    with Banco.abrir(BANCO_EM_MEMORIA) as vazio:
        with pytest.raises(ValueError, match="criar_schema"):
            vazio.gravar_transacoes([linha_de_transacao()])


def test_abrir_cria_o_diretorio_do_banco(tmp_path: Path) -> None:
    caminho = tmp_path / "dados" / "financas.duckdb"

    with Banco.abrir(caminho) as instancia:
        instancia.criar_schema()

    assert caminho.is_file()


# ---------------------------------------------------------------------------
# Idempotência
# ---------------------------------------------------------------------------


def test_gravar_duas_vezes_nao_duplica(
    banco: Banco, dados_normalizados: dict[str, list[dict[str, Any]]]
) -> None:
    banco.gravar_transacoes(dados_normalizados["transacoes"])
    banco.gravar_transacoes(dados_normalizados["transacoes"])

    assert banco.contar("raw_transacoes") == 27


def test_segunda_gravacao_nao_altera_nada(
    banco: Banco,
    relogio: RelogioFalso,
    dados_normalizados: dict[str, list[dict[str, Any]]],
) -> None:
    """O coração da idempotência: rodar de novo, horas depois, não muda o banco."""
    banco.gravar_transacoes(dados_normalizados["transacoes"])
    antes = banco.conexao.execute("SELECT * FROM raw_transacoes ORDER BY id").fetchall()

    relogio.avancar(hours=6)
    resultado = banco.gravar_transacoes(dados_normalizados["transacoes"])

    depois = banco.conexao.execute("SELECT * FROM raw_transacoes ORDER BY id").fetchall()
    assert depois == antes
    assert resultado.inseridas == 0
    assert resultado.atualizadas == 0
    assert resultado.inalteradas == 27
    assert resultado.houve_mudanca is False


def test_timestamps_de_controle_nao_se_mexem_a_toa(
    banco: Banco, relogio: RelogioFalso
) -> None:
    banco.gravar_transacoes([linha_de_transacao()])
    relogio.avancar(days=3)
    banco.gravar_transacoes([linha_de_transacao()])

    ingerido, atualizado = banco.conexao.execute(
        "SELECT ingerido_em, atualizado_em FROM raw_transacoes"
    ).fetchone()

    assert ingerido == datetime(2025, 9, 20, 10, 0, 0)
    assert atualizado == datetime(2025, 9, 20, 10, 0, 0)


def test_primeira_gravacao_conta_como_insercao(banco: Banco) -> None:
    resultado = banco.gravar_transacoes([linha_de_transacao("tx-1"), linha_de_transacao("tx-2")])

    assert resultado.inseridas == 2
    assert resultado.atualizadas == 0
    assert resultado.houve_mudanca is True


# ---------------------------------------------------------------------------
# Atualização real
# ---------------------------------------------------------------------------


def test_transacao_que_mudou_e_atualizada(banco: Banco, relogio: RelogioFalso) -> None:
    """A Pluggy atualiza transação: PENDING vira POSTED, valor de cartão muda
    antes de a fatura fechar. Sobrescrever é o comportamento certo."""
    banco.gravar_transacoes([linha_de_transacao(situacao="PENDING")])
    relogio.avancar(days=1)

    resultado = banco.gravar_transacoes([linha_de_transacao(situacao="POSTED")])

    situacao, ingerido, atualizado = banco.conexao.execute(
        "SELECT situacao, ingerido_em, atualizado_em FROM raw_transacoes"
    ).fetchone()
    assert resultado.atualizadas == 1
    assert situacao == "POSTED"
    assert ingerido == datetime(2025, 9, 20, 10, 0, 0)  # preservado
    assert atualizado == datetime(2025, 9, 21, 10, 0, 0)  # avançou


def test_valor_corrigido_sobrescreve(banco: Banco) -> None:
    banco.gravar_transacoes([linha_de_transacao(valor=Decimal("-100.00"))])
    banco.gravar_transacoes([linha_de_transacao(valor=Decimal("-150.00"))])

    (valor,) = banco.conexao.execute("SELECT valor FROM raw_transacoes").fetchone()
    assert valor == Decimal("-150.00")
    assert banco.contar("raw_transacoes") == 1


def test_lote_com_novas_e_repetidas_conta_certo(banco: Banco) -> None:
    banco.gravar_transacoes([linha_de_transacao("tx-1"), linha_de_transacao("tx-2")])

    resultado = banco.gravar_transacoes(
        [
            linha_de_transacao("tx-1"),                      # igual
            linha_de_transacao("tx-2", situacao="PENDING"),  # mudou
            linha_de_transacao("tx-3"),                      # nova
        ]
    )

    assert (resultado.inseridas, resultado.atualizadas, resultado.inalteradas) == (1, 1, 1)


# ---------------------------------------------------------------------------
# Deduplicação dentro do lote
# ---------------------------------------------------------------------------


def test_id_repetido_no_mesmo_lote_nao_estoura(banco: Banco) -> None:
    """Páginas sobrepostas trazem a mesma transação duas vezes, e o ON CONFLICT
    do DuckDB recusa atualizar a mesma linha duas vezes na mesma instrução."""
    resultado = banco.gravar_transacoes(
        [linha_de_transacao("tx-1"), linha_de_transacao("tx-1")]
    )

    assert banco.contar("raw_transacoes") == 1
    assert resultado.recebidas == 2
    assert resultado.inseridas == 1


def test_repetida_no_lote_mantem_a_ultima_versao(banco: Banco) -> None:
    banco.gravar_transacoes(
        [
            linha_de_transacao("tx-1", situacao="PENDING"),
            linha_de_transacao("tx-1", situacao="POSTED"),
        ]
    )

    (situacao,) = banco.conexao.execute("SELECT situacao FROM raw_transacoes").fetchone()
    assert situacao == "POSTED"


def test_lote_vazio_nao_faz_nada(banco: Banco) -> None:
    resultado = banco.gravar_transacoes([])

    assert resultado.recebidas == 0
    assert resultado.houve_mudanca is False


# ---------------------------------------------------------------------------
# Snapshot diário de conta e investimento
# ---------------------------------------------------------------------------


def test_mesma_conta_em_dias_diferentes_gera_duas_linhas(banco: Banco) -> None:
    """É isto que torna possível a série histórica de patrimônio."""
    banco.gravar_contas([linha_de_conta(data_posicao=date(2025, 9, 20), saldo=Decimal("100.00"))])
    banco.gravar_contas([linha_de_conta(data_posicao=date(2025, 9, 21), saldo=Decimal("250.00"))])

    historico = banco.conexao.execute(
        "SELECT data_posicao, saldo FROM raw_contas ORDER BY data_posicao"
    ).fetchall()

    assert historico == [
        (date(2025, 9, 20), Decimal("100.00")),
        (date(2025, 9, 21), Decimal("250.00")),
    ]


def test_mesma_conta_no_mesmo_dia_atualiza_em_vez_de_duplicar(banco: Banco) -> None:
    """Rodar a ingestão duas vezes no mesmo dia não pode inventar um ponto novo
    na série — só corrigir o do dia."""
    banco.gravar_contas([linha_de_conta(saldo=Decimal("100.00"))])
    resultado = banco.gravar_contas([linha_de_conta(saldo=Decimal("250.00"))])

    assert banco.contar("raw_contas") == 1
    assert resultado.atualizadas == 1


def test_snapshot_de_conta_e_idempotente(banco: Banco, relogio: RelogioFalso) -> None:
    banco.gravar_contas([linha_de_conta()])
    antes = banco.conexao.execute("SELECT * FROM raw_contas").fetchall()

    relogio.avancar(hours=2)
    banco.gravar_contas([linha_de_conta()])

    assert banco.conexao.execute("SELECT * FROM raw_contas").fetchall() == antes


def test_investimentos_das_fixtures_gravam(
    banco: Banco, dados_normalizados: dict[str, list[dict[str, Any]]]
) -> None:
    resultado = banco.gravar_investimentos(dados_normalizados["investimentos"])

    assert resultado.inseridas == 2
    assert banco.contar("raw_investimentos") == 2


def test_investimento_nao_encosta_em_transacao(
    banco: Banco, dados_normalizados: dict[str, list[dict[str, Any]]]
) -> None:
    """Armadilha 3: aporte não é despesa. As tabelas são separadas por
    construção, e nada em raw_investimentos entra em raw_transacoes."""
    banco.gravar_transacoes(dados_normalizados["transacoes"])
    banco.gravar_investimentos(dados_normalizados["investimentos"])

    ids_investimento = {
        linha[0] for linha in banco.conexao.execute("SELECT id FROM raw_investimentos").fetchall()
    }
    ids_transacao = {
        linha[0] for linha in banco.conexao.execute("SELECT id FROM raw_transacoes").fetchall()
    }

    assert not ids_investimento & ids_transacao


# ---------------------------------------------------------------------------
# Integridade dos dados gravados
# ---------------------------------------------------------------------------


def test_dinheiro_sobrevive_como_decimal(
    banco: Banco, dados_normalizados: dict[str, list[dict[str, Any]]]
) -> None:
    banco.gravar_transacoes(dados_normalizados["transacoes"])

    (total,) = banco.conexao.execute(
        "SELECT sum(valor) FROM raw_transacoes WHERE instituicao = 'Nubank'"
    ).fetchone()

    assert isinstance(total, Decimal)
    # 7 lançamentos da conta corrente mais 5 do cartão, conferidos à mão
    # contra as fixtures.
    assert total == Decimal("5759.75")


def test_payload_original_fica_recuperavel(banco: Banco) -> None:
    """'Raw é sagrado': campo que a normalização não previu continua no banco."""
    linha = linha_de_transacao()
    linha["payload_json"] = serializar({"id": "tx-1", "campoNovoDaPluggy": 42})

    banco.gravar_transacoes([linha])

    (payload,) = banco.conexao.execute(
        "SELECT payload_json FROM raw_transacoes"
    ).fetchone()
    assert "campoNovoDaPluggy" in payload


def test_procedencia_e_gravada(
    banco: Banco, dados_normalizados: dict[str, list[dict[str, Any]]]
) -> None:
    banco.gravar_transacoes(dados_normalizados["transacoes"])

    instituicoes = {
        linha[0]
        for linha in banco.conexao.execute(
            "SELECT DISTINCT instituicao FROM raw_transacoes"
        ).fetchall()
    }

    assert instituicoes == {"PicPay", "Santander", "Nubank", "Inter", "Rico Investimentos"}


# ---------------------------------------------------------------------------
# Configuração espelhada em cfg_*
# ---------------------------------------------------------------------------


def test_regras_viram_tabelas(banco: Banco, config_offline: Configuracao) -> None:
    banco.gravar_regras(config_offline.regras)

    assert banco.contar("cfg_padroes_fatura") == 5
    assert banco.contar("cfg_contrapartes_proprias") == 4
    assert banco.contar("cfg_frescor") == 1


def test_geral_vira_pares_chave_valor(banco: Banco, config_offline: Configuracao) -> None:
    banco.gravar_regras(config_offline.regras)

    valores = dict(banco.conexao.execute("SELECT chave, valor FROM cfg_geral").fetchall())

    assert valores["data_inicial"] == "2025-08-01"
    assert valores["frescor_dias_padrao"] == "5"


def test_carregar_regras_duas_vezes_nao_duplica(
    banco: Banco, config_offline: Configuracao
) -> None:
    banco.gravar_regras(config_offline.regras)
    banco.gravar_regras(config_offline.regras)

    assert banco.contar("cfg_padroes_fatura") == 5


def test_padrao_removido_do_toml_some_do_banco(
    banco: Banco, config_offline: Configuracao
) -> None:
    """A reescrita completa existe para isto: merge incremental deixaria no
    banco um filtro que já foi apagado do arquivo."""
    from dataclasses import replace

    banco.gravar_regras(config_offline.regras)
    banco.gravar_regras(replace(config_offline.regras, padroes_fatura=()))

    assert banco.contar("cfg_padroes_fatura") == 0


def test_padroes_chegam_em_minusculas_para_o_join(
    banco: Banco, config_offline: Configuracao
) -> None:
    """As views comparam com lower(); padrão em maiúscula nunca casaria."""
    banco.gravar_regras(config_offline.regras)

    padroes = [
        linha[0]
        for linha in banco.conexao.execute("SELECT padrao FROM cfg_padroes_fatura").fetchall()
    ]

    assert all(p == p.lower() for p in padroes)
