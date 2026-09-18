"""Contratos analíticos com valores sintéticos calculados independentemente."""
from datetime import date
from decimal import Decimal
import json

import pytest

from conftest import RAIZ
from financas.views import aplicar_views


@pytest.fixture
def analitico(banco, config_offline):
    banco.gravar_regras(config_offline.regras)
    banco.gravar_contas([dict(id="cc", data_posicao=date(2025, 9, 20), instituicao="Banco teste", tipo="CREDIT", nome="Cartão", moeda="BRL", payload_json="{}"), dict(id="vazia", data_posicao=date(2025, 9, 20), instituicao="Sem movimento", tipo="BANK", nome="Conta", moeda="BRL", payload_json="{}")])
    aplicar_views(banco, RAIZ / "sql")
    return banco


def transacao(banco, id="t1", **campos):
    linha = dict(id=id, id_conta="cc", instituicao="Banco teste", descricao="Loja", descricao_original="LOJA ORIGINAL", valor=Decimal("100"), moeda="BRL", tipo="DEBIT", data=date(2025, 8, 10), situacao="POSTED", payload_json="{}")
    linha.update(campos)
    banco.gravar_transacoes([linha])


def test_conservacao_conversao_e_auditoria(analitico):
    transacao(analitico)
    transacao(analitico, "usd", moeda="USD", valor=Decimal("10"), payload_json=json.dumps({"amountInAccountCurrency": 52.35, "creditCardMetadata": {"purchaseDate": "2025-08-01", "totalAmount": 1200, "billId": "f1"}}))
    transacao(analitico, "sem_cambio", moeda="USD", valor=Decimal("10"))
    transacao(analitico, "futuro", data=date(2099, 1, 1), parcela_numero=2, parcela_total=12)
    assert analitico.contar("transacoes_analiticas") == 4
    assert analitico.contar("gastos_analiticos") == 3
    assert analitico.conexao.execute("select sum(valor_brl) from gastos_analiticos").fetchone()[0] == Decimal("152.35")
    assert analitico.conexao.execute("select valor_original, valor_assinado_brl, data_compra_fonte, valor_total_fonte, id_fatura from transacoes_analiticas where id_transacao='usd'").fetchone() == (Decimal("10"), Decimal("-52.35"), date(2025, 8, 1), Decimal("1200"), "f1")
    assert analitico.conexao.execute("select valor_brl from transacoes_analiticas where id_transacao='sem_cambio'").fetchone() == (None,)


def test_parcelas_nao_sao_recorrencias_nem_compras_sem_confirmacao(analitico):
    for n in range(1, 4):
        transacao(analitico, f"p{n}", data=date(2025, n, 10), parcela_numero=n, parcela_total=12)
    assert analitico.contar("recorrencias") == 0
    assert analitico.contar("recorrencias_analiticas") == 0
    assert analitico.contar("compras") == 0


def test_qualidade_nao_inventa_falha_em_conta_sem_movimento(analitico):
    transacao(analitico, "futuro", data=date(2099, 1, 1))
    assert analitico.conexao.execute("select situacao, ultima_transacao from qualidade_dados where instituicao='Sem movimento'").fetchone() == ("sem_movimento", None)
    assert analitico.conexao.execute("select ultima_transacao from qualidade_dados where instituicao='Banco teste'").fetchone() == (None,)


def test_conservacao_exata_do_legado(banco_com_views):
    c = banco_com_views.conexao
    assert c.execute("select id_transacao, valor from gastos order by 1").fetchall() == c.execute("select id_transacao, valor_original from gastos_analiticos order by 1").fetchall()


def test_cambio_nao_presumido_em_conta_estrangeira(analitico):
    analitico.conexao.execute("update raw_contas set moeda='USD' where id='cc'")
    transacao(analitico, moeda="USD", payload_json='{"amountInAccountCurrency": 25}')
    assert analitico.conexao.execute("select valor_brl from gastos_analiticos").fetchone() == (None,)


def test_posicao_investimento_sem_conta_e_log_sao_distintos(analitico):
    analitico.gravar_investimentos([dict(id="inv", data_posicao=date(2025, 9, 20), instituicao="Investimentos teste", payload_json="{}")])
    assert analitico.conexao.execute("select data_posicao, sincronizacao_estado, ultima_sincronizacao from qualidade_dados where instituicao='Investimentos teste'").fetchone() == (date(2025, 9, 20), "sem_registro", None)
    analitico.conexao.execute("insert into log_sincronizacoes values ('Investimentos teste', '2025-09-21 10:00:00', '2025-09-20 10:00:00', '2025-08-01', '2025-09-20', 'falha', 'Falha sintética')")
    assert analitico.conexao.execute("select sincronizacao_estado, cobertura_desde, cobertura_ate from qualidade_dados where instituicao='Investimentos teste'").fetchone() == ("falha", date(2025, 8, 1), date(2025, 9, 20))


def test_compra_avulsa_prefere_data_compra_da_fonte(analitico):
    transacao(analitico, payload_json='{"creditCardMetadata":{"purchaseDate":"2025-08-01"}}')
    assert analitico.conexao.execute("select data from compras").fetchone() == (date(2025, 8, 1),)


def test_recorrencia_mesmo_nome_com_caixa_diferente_nao_duplica_custo(analitico):
    from financas.personalizacoes import aplicar_ajuste
    transacao(analitico, "mes1", descricao="Loja", descricao_original="Loja", data=date(2025, 1, 10))
    transacao(analitico, "mes2", descricao="LOJA", descricao_original="LOJA", data=date(2025, 2, 10))
    aplicar_ajuste(analitico, {"tipo": "recorrencia", "instituicao": "Banco teste", "estabelecimento": "Loja", "estado": "ativa"})
    assert analitico.conexao.execute("SELECT meses_observados, custo_anual_estimado_brl FROM recorrencias_analiticas").fetchall() == [(2, Decimal("1200"))]


def test_recorrencia_por_conta_nao_atribui_todos_gastos_a_primeira_conta(analitico):
    for mes in [1, 2]:
        transacao(analitico, f"a{mes}", data=date(2025, mes, 10), valor=Decimal("100"))
        transacao(analitico, f"b{mes}", id_conta="outra", data=date(2025, mes, 10), valor=Decimal("300"))
    assert analitico.conexao.execute("SELECT id_conta, valor_medio_brl FROM recorrencias_analiticas ORDER BY id_conta").fetchall() == [("cc", Decimal("100")), ("outra", Decimal("300"))]
