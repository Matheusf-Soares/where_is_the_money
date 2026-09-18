"""A finalidade de uma despesa pode variar mesmo na mesma categoria."""
from financas.personalizacoes import aplicar_ajuste


def test_atributos_individuais_independem_da_categoria(banco_com_views):
    aplicar_ajuste(banco_com_views, {"tipo": "classificacao", "ids_transacoes": ["tx-nu-c-01", "tx-nu-c-02"], "id_categoria": "transporte-aplicativo"})
    aplicar_ajuste(banco_com_views, {"tipo": "atributos", "ids_transacoes": ["tx-nu-c-01"], "essencialidade": "essencial", "comportamento": "variavel"})
    resultado = banco_com_views.conexao.execute("SELECT id_transacao, essencialidade, comportamento FROM transacoes_analiticas WHERE id_transacao IN ('tx-nu-c-01', 'tx-nu-c-02') ORDER BY id_transacao").fetchall()
    assert resultado == [("tx-nu-c-01", "essencial", "variavel"), ("tx-nu-c-02", "nao_definido", "nao_definido")]
    banco_com_views.criar_schema()
    assert banco_com_views.conexao.execute("SELECT essencialidade FROM transacoes_analiticas WHERE id_transacao='tx-nu-c-01'").fetchone()[0] == "essencial"
    aplicar_ajuste(banco_com_views, {"tipo": "atributos", "ids_transacoes": ["tx-nu-c-01"], "essencialidade": "discricionario", "comportamento": "fixo"})
    aplicar_ajuste(banco_com_views, {"tipo": "desfazer_atributos", "ids_transacoes": ["tx-nu-c-01"]})
    assert banco_com_views.conexao.execute("SELECT essencialidade FROM transacoes_analiticas WHERE id_transacao='tx-nu-c-01'").fetchone()[0] == "essencial"
    aplicar_ajuste(banco_com_views, {"tipo": "desfazer_atributos", "ids_transacoes": ["tx-nu-c-01"]})
    assert banco_com_views.conexao.execute("SELECT essencialidade FROM transacoes_analiticas WHERE id_transacao='tx-nu-c-01'").fetchone()[0] == "nao_definido"


def test_forma_pagamento_vem_da_fonte_sem_confundir_categoria(banco_com_views):
    banco_com_views.conexao.execute("UPDATE raw_transacoes SET payload_json=json_merge_patch(payload_json::JSON, '{\"paymentData\":{\"paymentMethod\":\"PIX\"}}')::VARCHAR WHERE id='tx-nu-c-01'")
    assert banco_com_views.conexao.execute("SELECT forma_pagamento FROM transacoes_analiticas WHERE id_transacao='tx-nu-c-01'").fetchone() == ("PIX",)
