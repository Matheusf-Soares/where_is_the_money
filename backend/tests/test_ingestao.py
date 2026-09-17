"""
Testes da orquestração da ingestão.

Dois comportamentos concentram o valor: a travessia completa
`item → conta → transação` e o isolamento de falha por instituição — o
consentimento vencido de um banco não pode impedir a ingestão dos outros.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest

from financas.config import Configuracao
from financas.ingestao import ingerir
from financas.persistencia import Banco
from financas.pluggy import ClienteFixtures, ConsentimentoExpirado, criar_cliente

HOJE = date(2025, 9, 20)


class ClienteComFalha:
    """Envelopa um cliente e faz uma instituição específica falhar.

    Reproduz a armadilha 4 na forma barulhenta: a API recusa o acesso a um item
    porque o consentimento venceu.
    """

    def __init__(self, interno: ClienteFixtures, id_item_quebrado: str) -> None:
        self._interno = interno
        self._quebrado = id_item_quebrado

    def listar_itens(self) -> list[dict[str, Any]]:
        return self._interno.listar_itens()

    def listar_contas(self, id_item: str) -> list[dict[str, Any]]:
        if id_item == self._quebrado:
            raise ConsentimentoExpirado(f"HTTP 403 em {id_item}")
        return self._interno.listar_contas(id_item)

    def listar_transacoes(self, id_conta: str, desde: date) -> Iterator[dict[str, Any]]:
        return self._interno.listar_transacoes(id_conta, desde)

    def listar_investimentos(self, id_item: str) -> list[dict[str, Any]]:
        return self._interno.listar_investimentos(id_item)


class ClienteComItemDoente:
    """Envelopa um cliente e adultera o estado de um item.

    Serve para exercitar a leitura de saúde sem inventar uma fixture nova: o
    que se testa é a reação a `status`, `userAction` e afins, não a travessia.
    """

    def __init__(self, interno: ClienteFixtures, **campos: Any) -> None:
        self._interno = interno
        self._campos = campos

    def listar_itens(self) -> list[dict[str, Any]]:
        itens = [dict(i) for i in self._interno.listar_itens()]
        itens[0].update(self._campos)
        return itens

    def listar_contas(self, id_item: str) -> list[dict[str, Any]]:
        return self._interno.listar_contas(id_item)

    def listar_transacoes(self, id_conta: str, desde: date) -> Iterator[dict[str, Any]]:
        return self._interno.listar_transacoes(id_conta, desde)

    def listar_investimentos(self, id_item: str) -> list[dict[str, Any]]:
        return self._interno.listar_investimentos(id_item)


@pytest.fixture
def cliente(config_offline: Configuracao) -> ClienteFixtures:
    return criar_cliente(config_offline)


# ---------------------------------------------------------------------------
# Saúde do item: a armadilha 4, um passo antes
# ---------------------------------------------------------------------------


def test_item_inexistente_e_falha_nao_excecao(
    banco: Banco, cliente: ClienteFixtures, config_offline: Configuracao
) -> None:
    """Id morto é rotina, e rotina não pode abortar as outras instituições.

    Reautorizar gera um itemId novo (armadilha 8), então `/items/{id}` vai
    responder 404 mais cedo ou mais tarde. Quando isso acontecer, as outras
    quatro instituições têm que ser ingeridas normalmente.
    """
    doente = ClienteComItemDoente(cliente, status="NOT_FOUND")

    resumo = ingerir(doente, banco, config_offline.regras, hoje=HOJE)

    assert resumo.houve_falha
    assert len(resumo.falhas) == 1
    assert "não existe mais" in resumo.falhas[0].motivo
    # E o resto entrou: 5 items menos o morto.
    assert resumo.contas > 0
    assert resumo.transacoes.inseridas > 0


def test_item_que_pede_acao_do_usuario_e_reportado(
    banco: Banco, cliente: ClienteFixtures, config_offline: Configuracao
) -> None:
    """A API avisa ANTES de parar de trazer dado, e o aviso não era lido.

    `userAction` preenchido significa MFA pendente ou senha trocada. O dado de
    hoje vem; o de amanhã não. Sem isto, você descobriria pelo `frescor` uma
    semana depois.
    """
    doente = ClienteComItemDoente(
        cliente, status="WAITING_USER_INPUT", userAction="INPUT_MFA"
    )

    resumo = ingerir(doente, banco, config_offline.regras, hoje=HOJE)

    assert not resumo.houve_falha  # o dado veio
    assert resumo.houve_degradacao
    assert "INPUT_MFA" in resumo.degradados[0].diagnostico
    assert "WAITING_USER_INPUT" in resumo.degradados[0].diagnostico


def test_login_falhando_em_sequencia_e_reportado(
    banco: Banco, cliente: ClienteFixtures, config_offline: Configuracao
) -> None:
    """Conexão degradando antes de cair."""
    doente = ClienteComItemDoente(cliente, consecutiveFailedLoginAttempts=3)

    resumo = ingerir(doente, banco, config_offline.regras, hoje=HOJE)

    assert resumo.houve_degradacao
    assert "3 login" in resumo.degradados[0].diagnostico


def test_item_saudavel_nao_gera_ruido(
    banco: Banco, cliente: ClienteFixtures, config_offline: Configuracao
) -> None:
    """Alerta que dispara sempre é alerta que ninguém lê."""
    resumo = ingerir(cliente, banco, config_offline.regras, hoje=HOJE)

    assert not resumo.houve_falha
    assert not resumo.houve_degradacao


# ---------------------------------------------------------------------------
# Travessia completa
# ---------------------------------------------------------------------------


def test_ingere_tudo_das_fixtures(
    cliente: ClienteFixtures, banco: Banco, config_offline: Configuracao
) -> None:
    resumo = ingerir(cliente, banco, config_offline.regras, hoje=HOJE)

    assert resumo.itens == 5
    assert resumo.contas == 8
    assert resumo.transacoes.inseridas == 27
    assert resumo.investimentos.inseridas == 2
    assert resumo.houve_falha is False


def test_data_inicial_das_regras_e_respeitada(
    cliente: ClienteFixtures, banco: Banco, config_offline: Configuracao
) -> None:
    """Armadilha 9: não existe histórico antes de agosto de 2025."""
    ingerir(cliente, banco, config_offline.regras, hoje=HOJE)

    (mais_antiga,) = banco.conexao.execute(
        "SELECT min(data) FROM raw_transacoes"
    ).fetchone()

    assert mais_antiga >= config_offline.regras.data_inicial


def test_desde_sobrescreve_a_data_inicial(
    cliente: ClienteFixtures, banco: Banco, config_offline: Configuracao
) -> None:
    resumo = ingerir(
        cliente, banco, config_offline.regras, hoje=HOJE, desde=date(2025, 9, 1)
    )

    # As 3 transações de agosto (2 do PicPay e 1 do Nubank) ficam de fora.
    assert resumo.transacoes.inseridas == 20


def test_posicao_das_contas_usa_a_data_informada(
    cliente: ClienteFixtures, banco: Banco, config_offline: Configuracao
) -> None:
    ingerir(cliente, banco, config_offline.regras, hoje=HOJE)

    datas = {
        linha[0]
        for linha in banco.conexao.execute(
            "SELECT DISTINCT data_posicao FROM raw_contas"
        ).fetchall()
    }

    assert datas == {HOJE}


def test_procedencia_chega_ate_a_transacao(
    cliente: ClienteFixtures, banco: Banco, config_offline: Configuracao
) -> None:
    ingerir(cliente, banco, config_offline.regras, hoje=HOJE)

    (instituicao, id_item) = banco.conexao.execute(
        "SELECT instituicao, id_item FROM raw_transacoes WHERE id = 'tx-in-b-02'"
    ).fetchone()

    assert instituicao == "Inter"
    assert id_item == "item-inter"


# ---------------------------------------------------------------------------
# Idempotência de ponta a ponta
# ---------------------------------------------------------------------------


def test_ingerir_duas_vezes_nao_muda_o_banco(
    cliente: ClienteFixtures, banco: Banco, config_offline: Configuracao, relogio
) -> None:
    ingerir(cliente, banco, config_offline.regras, hoje=HOJE)
    antes = banco.conexao.execute("SELECT * FROM raw_transacoes ORDER BY id").fetchall()

    relogio.avancar(hours=4)
    segunda = ingerir(cliente, banco, config_offline.regras, hoje=HOJE)

    assert banco.conexao.execute(
        "SELECT * FROM raw_transacoes ORDER BY id"
    ).fetchall() == antes
    assert segunda.transacoes.inseridas == 0
    assert segunda.transacoes.inalteradas == 27


def test_ingerir_em_outro_dia_cria_novo_retrato_de_conta(
    cliente: ClienteFixtures, banco: Banco, config_offline: Configuracao
) -> None:
    """Transação não duplica, mas conta ganha um ponto novo na série."""
    ingerir(cliente, banco, config_offline.regras, hoje=HOJE)
    ingerir(cliente, banco, config_offline.regras, hoje=date(2025, 9, 21))

    assert banco.contar("raw_transacoes") == 27
    assert banco.contar("raw_contas") == 16


# ---------------------------------------------------------------------------
# Isolamento de falha
# ---------------------------------------------------------------------------


def test_instituicao_com_consentimento_vencido_nao_derruba_as_outras(
    cliente: ClienteFixtures, banco: Banco, config_offline: Configuracao
) -> None:
    quebrado = ClienteComFalha(cliente, "item-nubank")

    resumo = ingerir(quebrado, banco, config_offline.regras, hoje=HOJE)

    assert resumo.houve_falha is True
    assert [f.instituicao for f in resumo.falhas] == ["Nubank"]
    # As outras 4 instituições entraram: 27 transações menos as 12 do Nubank.
    assert resumo.transacoes.inseridas == 15
    assert banco.contar("raw_transacoes") == 15


def test_nada_do_nubank_entrou_pela_metade(
    cliente: ClienteFixtures, banco: Banco, config_offline: Configuracao
) -> None:
    quebrado = ClienteComFalha(cliente, "item-nubank")

    ingerir(quebrado, banco, config_offline.regras, hoje=HOJE)

    (quantas,) = banco.conexao.execute(
        "SELECT count(*) FROM raw_transacoes WHERE instituicao = 'Nubank'"
    ).fetchone()
    assert quantas == 0


def test_rodar_de_novo_apos_resolver_completa_o_que_faltou(
    cliente: ClienteFixtures, banco: Banco, config_offline: Configuracao
) -> None:
    """É por isso que a falha parcial não é grave: a ingestão é idempotente."""
    ingerir(ClienteComFalha(cliente, "item-nubank"), banco, config_offline.regras, hoje=HOJE)

    resumo = ingerir(cliente, banco, config_offline.regras, hoje=HOJE)

    assert resumo.houve_falha is False
    assert resumo.transacoes.inseridas == 12  # só as do Nubank faltavam
    assert banco.contar("raw_transacoes") == 27
