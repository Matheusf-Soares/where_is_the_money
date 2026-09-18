"""Uma publicação incompleta nunca substitui o retrato que a tela está lendo."""
import json

import pytest

from financas import publicacao


def test_manifesto_aponta_para_arquivos_imutaveis(banco_com_views, tmp_path):
    publicacao.publicar(banco_com_views, tmp_path)
    primeiro = json.loads((tmp_path / 'manifesto.json').read_text(encoding='utf-8'))
    assert primeiro['versao_schema'] == 2
    arquivo = tmp_path / primeiro['arquivos']['gastos']
    antes = arquivo.read_bytes()
    banco_com_views.conexao.execute("UPDATE raw_transacoes SET valor = -42 WHERE id = 'tx-nu-c-01'")
    publicacao.publicar(banco_com_views, tmp_path)
    segundo = json.loads((tmp_path / 'manifesto.json').read_text(encoding='utf-8'))
    assert segundo['versao'] != primeiro['versao']
    assert arquivo.read_bytes() == antes
    assert (tmp_path / segundo['arquivos']['gastos']).is_file()


def test_falha_na_exportacao_preserva_manifesto_e_dados(banco_com_views, tmp_path, monkeypatch):
    publicacao.publicar(banco_com_views, tmp_path)
    anterior = (tmp_path / 'manifesto.json').read_bytes()
    original = publicacao._exportar_tabela

    def falhar(banco, tabela, arquivo):
        if tabela == 'stg_transacoes':
            raise OSError('falha de disco simulada')
        return original(banco, tabela, arquivo)

    monkeypatch.setattr(publicacao, '_exportar_tabela', falhar)
    with pytest.raises(publicacao.ErroDePublicacao):
        publicacao.publicar(banco_com_views, tmp_path)
    assert (tmp_path / 'manifesto.json').read_bytes() == anterior
    for caminho in json.loads(anterior)['arquivos'].values():
        assert (tmp_path / caminho).is_file()


def test_periodo_realizado_nao_inclui_parcelas_futuras(banco_com_views, tmp_path):
    banco_com_views.conexao.execute("UPDATE raw_transacoes SET data = DATE '2099-01-01' WHERE id = 'tx-nu-c-01'")
    publicacao.publicar(banco_com_views, tmp_path)
    manifesto = json.loads((tmp_path / 'manifesto.json').read_text(encoding='utf-8'))
    assert manifesto['periodo']['ultima_transacao'] < '2099-01-01'
    assert manifesto['periodo']['ultima_futura'] == '2099-01-01'


def test_falha_de_limpeza_nao_mascara_erro_de_publicacao(banco_com_views, tmp_path, monkeypatch):
    from pathlib import Path
    publicacao.publicar(banco_com_views, tmp_path)
    anterior = (tmp_path / "manifesto.json").read_bytes()
    original_exportar = publicacao._exportar_tabela
    original_apagar = Path.unlink
    def exportar(banco, tabela, arquivo):
        if tabela == "stg_transacoes":
            raise OSError("falha sintética de exportação")
        original_exportar(banco, tabela, arquivo)
    def apagar(arquivo, *args, **kwargs):
        if arquivo.suffix == ".parquet":
            raise PermissionError("arquivo ocupado")
        return original_apagar(arquivo, *args, **kwargs)
    monkeypatch.setattr(publicacao, "_exportar_tabela", exportar)
    monkeypatch.setattr(Path, "unlink", apagar)
    with pytest.raises(publicacao.ErroDePublicacao, match="exportação"):
        publicacao.publicar(banco_com_views, tmp_path)
    assert (tmp_path / "manifesto.json").read_bytes() == anterior
