"""Prévia parcial: não mistura ciclos, pagamentos nem moedas sem conversão."""
import json
from datetime import date
from decimal import Decimal

import pytest

from financas.publicacao import publicar
from test_analiticos import analitico, transacao


def fechar(banco):
    banco.gravar_faturas([dict(id="f-fechada", id_conta="cc", instituicao="Banco teste",
        vencimento=date(2025, 9, 10), fechamento=date(2025, 9, 2),
        valor_total=Decimal("9999"), moeda="BRL", payload_json="{}")])


def pendente(banco, identificador="p1", previsao="2025-10", **campos):
    metadados = {"billForecastDate": previsao}
    metadados.update(campos.pop("metadados", {}))
    payload = {"creditCardMetadata": metadados, **campos.pop("payload", {})}
    dados = dict(data=date(2025, 9, 4), situacao="PENDING", payload_json=json.dumps(payload))
    dados.update(campos)
    transacao(banco, identificador, **dados)


def test_previa_separa_creditos_pagamentos_e_moedas(analitico):
    fechar(analitico)
    pendente(analitico)
    pendente(analitico, "estorno", tipo="CREDIT", valor=Decimal("20"), payload={"operationType": "ESTORNO"})
    pendente(analitico, "pagamento", tipo="CREDIT", valor=Decimal("500"), payload={"operationType": "PAGAMENTO_FATURA"})
    pendente(analitico, "usd", moeda="USD", valor=Decimal("10"))
    pendente(analitico, "usd-convertido", moeda="USD", valor=Decimal("5"), payload={"amountInAccountCurrency": 25})
    row = analitico.conexao.execute("SELECT subtotal_despesas_brl, subtotal_creditos_brl, pagamentos_brl, liquido_conhecido_brl, qtd_lancamentos, qtd_sem_conversao, previa_parcial FROM faturas_abertas").fetchone()
    assert row == (Decimal("125"), Decimal("20"), Decimal("500"), Decimal("105"), 5, 1, True)
    assert analitico.conexao.execute("SELECT tipo_lancamento FROM lancamentos_fatura_aberta WHERE id_transacao='pagamento'").fetchone() == ("pagamento",)


def test_previa_nao_mistura_parcelas_futuras_nem_coortes_posteriores(analitico):
    fechar(analitico)
    pendente(analitico)
    pendente(analitico, "outra-coorte", previsao="2025-11")
    pendente(analitico, "futura", previsao="2099-01", data=date(2099, 1, 2), parcela_numero=2, parcela_total=12)
    pendente(analitico, "anterior", data=date(2025, 9, 1))
    pendente(analitico, "na-fechada", metadados={"billId": "f-fechada"})
    pendente(analitico, "conta-corrente", id_conta="vazia")
    assert analitico.conexao.execute("SELECT id_transacao, classificacao_periodo FROM lancamentos_fatura_aberta ORDER BY 1").fetchall() == [
        ("anterior", "anterior"), ("futura", "futura"), ("outra-coorte", "futura"), ("p1", "andamento")]
    assert analitico.conexao.execute("SELECT mes_previsao_fonte, subtotal_despesas_brl, qtd_futuras FROM faturas_abertas").fetchone() == ("2025-10", Decimal("100"), 2)


def test_fechamento_limite_ambiguo_e_previsao_inconsistente_ficam_auditaveis(analitico):
    fechar(analitico)
    pendente(analitico, "recente-inconsistente", previsao="2025-09")
    pendente(analitico, "limite-sem-previsao", previsao=None, data=date(2025, 9, 2))
    pendente(analitico, "limite-inconsistente", previsao="2025-09", data=date(2025, 9, 2))
    pendente(analitico, "limite-confiavel", previsao="2025-10", data=date(2025, 9, 2))
    pendente(analitico, "recente-sem-previsao", previsao=None)
    assert analitico.conexao.execute("SELECT id_transacao, incluida_previa FROM lancamentos_fatura_aberta ORDER BY 1").fetchall() == [
        ("limite-confiavel", True), ("limite-inconsistente", False), ("limite-sem-previsao", False),
        ("recente-inconsistente", True), ("recente-sem-previsao", True)]
    assert analitico.conexao.execute("SELECT subtotal_despesas_brl, qtd_sem_associacao, qtd_previsao_inconsistente FROM faturas_abertas").fetchone() == (Decimal("300"), 2, 2)


def test_sem_previsao_e_sem_fechamento_nao_inventa_periodo_nem_zero_oficial(analitico):
    pendente(analitico, previsao=None)
    pendente(analitico, "invalida", previsao="2025-99")
    assert analitico.conexao.execute("SELECT mes_previsao_fonte, ultimo_fechamento, subtotal_despesas_brl, liquido_conhecido_brl, qtd_sem_associacao FROM faturas_abertas").fetchone() == (None, None, None, None, 2)


def test_previsao_sem_fechamento_delimita_so_a_primeira_coorte(analitico):
    pendente(analitico)
    pendente(analitico, "posterior", previsao="2025-11")
    assert analitico.conexao.execute("SELECT subtotal_despesas_brl, qtd_lancamentos, qtd_futuras FROM faturas_abertas").fetchone() == (Decimal("100"), 1, 1)


def test_upsert_pending_para_posted_sai_da_previa_e_entra_no_detalhe_fechado(analitico):
    fechar(analitico)
    pendente(analitico)
    assert analitico.contar("lancamentos_fatura_aberta") == 1
    pendente(analitico, situacao="POSTED", metadados={"billId": "f-fechada"})
    assert analitico.contar("lancamentos_fatura_aberta") == 0
    assert analitico.conexao.execute("SELECT t.id_transacao FROM transacoes_analiticas t JOIN faturas f ON t.id_fatura=f.id_fatura AND t.id_conta=f.id_conta").fetchall() == [("p1",)]


def test_publicacao_preserva_previa_e_detalhe_no_mesmo_retrato(analitico, tmp_path):
    fechar(analitico)
    pendente(analitico)
    publicar(analitico, tmp_path)
    manifesto = json.loads((tmp_path / "manifesto.json").read_text(encoding="utf-8"))
    for nome in ("faturas_abertas", "lancamentos_fatura_aberta"):
        assert nome in manifesto["arquivos"]
        assert analitico.conexao.execute("SELECT count(*) FROM read_parquet(?)", [str(tmp_path / manifesto["arquivos"][nome])]).fetchone() == (1,)


@pytest.mark.parametrize("data,iso,nome", [("2025-09-01", 1, "segunda-feira"), ("2025-09-02", 2, "terça-feira"), ("2025-09-03", 3, "quarta-feira"), ("2025-09-04", 4, "quinta-feira"), ("2025-09-05", 5, "sexta-feira"), ("2025-09-06", 6, "sábado"), ("2025-09-07", 7, "domingo")])
def test_dia_semana_portugues_e_iso_preservam_data_lancamento(analitico, data, iso, nome):
    transacao(analitico, data=date.fromisoformat(data), payload_json='{"creditCardMetadata":{"purchaseDate":"2025-08-01"}}')
    assert analitico.conexao.execute("SELECT data, dia_semana_iso, dia_semana, data_gasto, origem_data_gasto, dia_semana_gasto, dia_semana_gasto_iso FROM transacoes_analiticas").fetchone() == (date.fromisoformat(data), iso, nome, date(2025, 8, 1), "purchaseDate", "sexta-feira", 5)
    assert analitico.conexao.execute("SELECT data, dia_semana_iso, dia_semana, data_gasto, origem_data_gasto FROM compras").fetchone() == (date(2025, 8, 1), 5, "sexta-feira", date(2025, 8, 1), "purchaseDate")


def test_data_gasto_sem_purchase_date_usa_lancamento_e_preserva_raw(analitico):
    payload = '{"creditCardMetadata":{"purchaseDate":"invalida"},"outro":true}'
    transacao(analitico, payload_json=payload)
    assert analitico.conexao.execute("SELECT data_gasto, origem_data_gasto, dia_semana_gasto_iso FROM transacoes_analiticas").fetchone() == (date(2025, 8, 10), "data", 7)
    assert analitico.conexao.execute("SELECT payload_json FROM raw_transacoes").fetchone() == (payload,)


def test_compra_confirmada_deriva_dia_da_data_final_confirmada(analitico):
    from financas.personalizacoes import aplicar_ajuste
    transacao(analitico, parcela_numero=1, parcela_total=2,
        payload_json='{"creditCardMetadata":{"purchaseDate":"2025-08-01"}}')
    aplicar_ajuste(analitico, dict(tipo="compra", ids_transacoes=["t1"],
        data_compra="2025-08-02", valor_total_brl="200", descricao="Compra teste", grupo_parcial=True))
    assert analitico.conexao.execute("SELECT data, data_gasto, dia_semana, dia_semana_gasto_iso, origem_data_gasto FROM compras").fetchone() == (date(2025, 8, 2), date(2025, 8, 2), "sábado", 6, "compra_confirmada")


def test_pagamento_generico_a_estabelecimento_nao_e_fatura(analitico):
    fechar(analitico)
    pendente(analitico, payload={"operationType": "PAGAMENTO"})
    pendente(analitico, "pagamento-texto", tipo="CREDIT", descricao="Fatura cartao", valor=Decimal("500"))
    assert analitico.conexao.execute("SELECT subtotal_despesas_brl, pagamentos_brl, liquido_conhecido_brl FROM faturas_abertas").fetchone() == (Decimal("100"), Decimal("500"), Decimal("100"))


def test_somente_moeda_sem_cambio_tem_totais_desconhecidos(analitico):
    fechar(analitico)
    pendente(analitico, moeda="USD")
    assert analitico.conexao.execute("SELECT subtotal_despesas_brl, liquido_conhecido_brl, qtd_lancamentos, qtd_sem_conversao FROM faturas_abertas").fetchone() == (None, None, 1, 1)


def test_cartao_sem_pendencias_continua_no_resumo_sem_total_inventado(analitico):
    assert analitico.conexao.execute("SELECT id_conta, qtd_lancamentos, liquido_conhecido_brl FROM faturas_abertas").fetchall() == [("cc", 0, None)]


def test_dados_nulos_nao_geram_data_ou_dia_inventado(analitico):
    pendente(analitico, data=None)
    assert analitico.conexao.execute("SELECT data_gasto, dia_semana, dia_semana_gasto_iso FROM transacoes_analiticas").fetchone() == (None, None, None)
    assert analitico.conexao.execute("SELECT incluida_previa, classificacao_periodo FROM lancamentos_fatura_aberta").fetchone() == (False, "sem_associacao")


@pytest.mark.parametrize("com_despesa_usd", [False, True], ids=["somente-pagamento", "pagamento-e-despesa-usd"])
def test_pagamento_brl_nao_comprova_total_do_ciclo(analitico, com_despesa_usd):
    fechar(analitico)
    pendente(analitico, "pagamento", tipo="CREDIT", valor=Decimal("500"),
        payload={"operationType": "PAGAMENTO_FATURA"})
    if com_despesa_usd:
        pendente(analitico, "despesa-usd", moeda="USD", valor=Decimal("10"))
    assert analitico.conexao.execute("SELECT subtotal_despesas_brl, subtotal_creditos_brl, liquido_conhecido_brl, pagamentos_brl FROM faturas_abertas").fetchone() == (None, None, None, Decimal("500"))


def test_pagamento_generico_em_creditos_separa_pagamentos_fracionados(analitico):
    fechar(analitico)
    pendente(analitico, "compra", valor=Decimal("100"), payload={"operationType": "PAGAMENTO"})
    pendente(analitico, "estorno", tipo="CREDIT", valor=Decimal("20"), payload={"operationType": "ESTORNO"})
    pendente(analitico, "parcial-a", tipo="CREDIT", descricao="Evento sintético Alfa", valor=Decimal("125"),
        payload={"operationType": "PAGAMENTO"})
    pendente(analitico, "parcial-b", tipo="CREDIT", descricao="Evento sintético Beta", valor=Decimal("375"),
        payload={"operationType": "PAGAMENTO"})
    assert analitico.conexao.execute("SELECT id_transacao, tipo_lancamento FROM lancamentos_fatura_aberta ORDER BY id_transacao").fetchall() == [
        ("compra", "despesa"), ("estorno", "credito"), ("parcial-a", "pagamento"), ("parcial-b", "pagamento")]
    assert analitico.conexao.execute("SELECT subtotal_despesas_brl, subtotal_creditos_brl, pagamentos_brl, liquido_conhecido_brl, qtd_pagamentos FROM faturas_abertas").fetchone() == (Decimal("100"), Decimal("20"), Decimal("500"), Decimal("80"), 2)
