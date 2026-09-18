from datetime import date
from decimal import Decimal
import json
import pytest

from test_analiticos import analitico, transacao


def api():
    from financas import personalizacoes
    return personalizacoes


def categoria(banco, nome="Teste"):
    return api().aplicar_ajuste(banco, dict(tipo="categoria", nome=nome, macro_categoria="Lazer"))["id"]


def test_catalogo_seed_idempotente_e_replay_preserva_usuario(analitico, config_offline):
    catalogo = api().obter_catalogo(analitico)
    assert len({c["macro_categoria"] for c in catalogo["categorias"]}) == 10
    id = categoria(analitico)
    analitico.criar_schema()
    analitico.gravar_regras(config_offline.regras)
    assert any(c["id"] == id for c in api().obter_catalogo(analitico)["categorias"])


def test_prioridades_undo_real_e_validacao_atomica(analitico):
    transacao(analitico, descricao="Netflix", id_categoria="09020000")
    a, b = categoria(analitico, "A"), categoria(analitico, "B")
    ajustar = lambda **args: api().aplicar_ajuste(analitico, args)
    atual = lambda: analitico.conexao.execute("select categoria, origem_da_categoria from transacoes_analiticas").fetchone()
    ajustar(tipo="mapa", id_categoria_pluggy="09020000", id_categoria=a)
    assert atual()[0] == "Streaming"
    ajustar(tipo="regra", prioridade=10, padrao="%netflix%", id_categoria=a)
    assert atual() == ("A", "regra_ui")
    ajustar(tipo="classificacao", ids_transacoes=["t1"], id_categoria=b)
    ajustar(tipo="classificacao", ids_transacoes=["t1"], id_categoria=a)
    ajustar(tipo="desfazer", ids_transacoes=["t1"])
    assert atual() == ("B", "manual")
    ajustar(tipo="desfazer", ids_transacoes=["t1"])
    assert atual() == ("A", "regra_ui")
    with pytest.raises(ValueError):
        ajustar(tipo="classificacao", ids_transacoes=["t1", "nao-existe"], id_categoria=b)
    assert atual() == ("A", "regra_ui")


def test_previsao_respeita_prioridade_e_manual(analitico):
    for id in ("t1", "t2", "t3"):
        transacao(analitico, id)
    a, b = categoria(analitico, "A"), categoria(analitico, "B")
    api().aplicar_ajuste(analitico, dict(tipo="classificacao", ids_transacoes=["t1"], id_categoria=a))
    regra = dict(tipo="regra", prioridade=10, padrao="%loja%", id_categoria=b)
    preview = api().prever_regra(analitico, regra)
    assert (preview["quantidade"], preview["protegidas_manualmente"], preview["valor_brl"]) == (2, 1, Decimal("200"))
    api().aplicar_ajuste(analitico, regra)
    assert analitico.conexao.execute("select count(*) from transacoes_analiticas where categoria='B'").fetchone()[0] == preview["quantidade"]
    assert api().prever_regra(analitico, dict(regra, prioridade=20, id_categoria=a))["quantidade"] == 0


def test_alias_exato_especifico_vence_global(analitico):
    transacao(analitico)
    for inst, nome in [("Banco teste", "Específico"), ("%", "Global")]:
        api().aplicar_ajuste(analitico, dict(tipo="alias", descricao_original="loja original", estabelecimento=nome, instituicao=inst))
    assert analitico.conexao.execute("select estabelecimento from transacoes_analiticas").fetchone()[0] == "Específico"


def test_compra_confirmada_total_unico_inclui_parcelas_futuras(analitico):
    for n in range(1, 13):
        transacao(analitico, f"p{n}", data=date(2025 if n == 1 else 2099, n, 10), parcela_numero=n, parcela_total=12)
    ajuste = dict(tipo="compra", ids_transacoes=[f"p{n}" for n in range(1, 13)], data_compra="2025-01-10", valor_total_brl="1200.00", descricao="Compra teste")
    id = api().aplicar_ajuste(analitico, ajuste)["id"]
    assert analitico.conexao.execute("select count(*), sum(valor_brl) from compras").fetchone() == (1, Decimal("1200"))
    assert len(json.loads(analitico.conexao.execute("select ids_transacoes from compras").fetchone()[0])) == 12
    with pytest.raises(ValueError):
        api().aplicar_ajuste(analitico, ajuste)
    api().aplicar_ajuste(analitico, dict(tipo="desfazer_compra", id_compra=id))
    assert analitico.contar("compras") == 0


def test_compra_invalida_nao_grava_e_grupo_parcial_exige_declaracao(analitico):
    transacao(analitico, parcela_numero=1, parcela_total=12)
    ajuste = dict(tipo="compra", ids_transacoes=["t1"], data_compra="2025-01-10", valor_total_brl="1200", descricao="Compra parcial")
    with pytest.raises(ValueError):
        api().aplicar_ajuste(analitico, ajuste)
    with pytest.raises(ValueError):
        api().aplicar_ajuste(analitico, dict(ajuste, grupo_parcial=True, valor_total_brl="50"))
    api().aplicar_ajuste(analitico, dict(ajuste, grupo_parcial=True))
    assert analitico.contar("compras") == 1


def test_recorrencia_manual_permanece_sem_limiar(analitico):
    transacao(analitico)
    api().aplicar_ajuste(analitico, dict(tipo="recorrencia", instituicao="Banco teste", estabelecimento="Loja", estado="ativa"))
    assert analitico.conexao.execute("select estado, meses_observados from recorrencias_analiticas").fetchone() == ("ativa", 1)


def test_preview_normaliza_textos_igual_a_gravacao_e_nao_persiste(analitico):
    transacao(analitico)
    id = categoria(analitico)
    api().aplicar_ajuste(analitico, dict(tipo="classificacao", ids_transacoes=["t1"], id_categoria=id))
    preview = api().prever_regra(analitico, dict(prioridade=1, padrao="  %loja%  ", instituicao="  %  ", id_categoria=id))
    assert preview["protegidas_manualmente"] == 1
    assert api().obter_catalogo(analitico)["regras"] == []


def test_preview_contagem_completa_e_amostra_limitada(analitico):
    for n in range(35):
        transacao(analitico, str(n))
    id = categoria(analitico)
    resultado = api().prever_regra(analitico, dict(prioridade=1, padrao="%loja%", id_categoria=id))
    assert resultado["quantidade"] == 35
    assert resultado["valor_brl"] == Decimal("3500")
    assert len(resultado["linhas"]) == 30
    assert api().obter_catalogo(analitico)["regras"] == []


@pytest.mark.parametrize("mudanca", [dict(data_compra="2099-01-01"), dict(valor_total_brl="NaN"), dict(valor_total_brl="-100"), dict(valor_total_brl="100.001"), dict(ids_transacoes=["ausente"]), dict(ids_transacoes=["t1", "t1"])])
def test_compra_rejeita_dados_invalidos_atomicamente(analitico, mudanca):
    transacao(analitico, parcela_numero=1, parcela_total=2)
    ajuste = dict(tipo="compra", ids_transacoes=["t1"], data_compra="2025-08-10", valor_total_brl="200", descricao="Compra", grupo_parcial=True)
    with pytest.raises(ValueError):
        api().aplicar_ajuste(analitico, dict(ajuste, **mudanca))
    assert api().obter_catalogo(analitico)["compras"] == []
    assert analitico.conexao.execute("select compra_pendente from transacoes_analiticas").fetchone() == (True,)


def test_manual_nunca_suplanta_exclusao_financeira(analitico):
    transacao(analitico, descricao="Aplicacao teste")
    id = categoria(analitico)
    api().aplicar_ajuste(analitico, dict(tipo="classificacao", ids_transacoes=["t1"], id_categoria=id))
    assert analitico.contar("gastos_analiticos") == 0
    assert analitico.conexao.execute("select origem_da_categoria, motivo_exclusao from transacoes_analiticas").fetchone() == ("manual", "aplicacao")


@pytest.mark.parametrize("mudanca", [dict(id_conta="outra"), dict(instituicao="Outro banco"), dict(parcela_numero=1), dict(parcela_total=3), dict(descricao="Aplicacao financeira"), dict(tipo="CREDIT"), dict(parcela_total=None)])
def test_compra_nao_agrupa_parcelas_incompativeis(analitico, mudanca):
    transacao(analitico, "p1", parcela_numero=1, parcela_total=2)
    valores = dict(parcela_numero=2, parcela_total=2)
    valores.update(mudanca)
    transacao(analitico, "p2", **valores)
    with pytest.raises(ValueError):
        api().aplicar_ajuste(analitico, dict(tipo="compra", ids_transacoes=["p1", "p2"], data_compra="2025-08-10", valor_total_brl="200", descricao="Compra"))
    assert api().obter_catalogo(analitico)["compras"] == []


def test_mapa_ui_vence_mapa_toml_e_undo_sem_historico_e_inerte(analitico):
    transacao(analitico, id_categoria="10000000")
    id = categoria(analitico)
    api().aplicar_ajuste(analitico, dict(tipo="mapa", id_categoria_pluggy="10000000", id_categoria=id))
    api().aplicar_ajuste(analitico, dict(tipo="desfazer", ids_transacoes=["t1"]))
    assert analitico.conexao.execute("select categoria, origem_da_categoria from transacoes_analiticas").fetchone() == ("Teste", "mapa_ui")


def test_recorrencia_confirmada_sem_observacoes_nao_inventa_cancelamento(analitico):
    api().aplicar_ajuste(analitico, dict(tipo="recorrencia", instituicao="Banco teste", estabelecimento="Loja", estado="ativa"))
    assert analitico.conexao.execute("select estado, meses_observados, custo_anual_estimado_brl from recorrencias_analiticas").fetchone() == ("ativa", 0, None)
