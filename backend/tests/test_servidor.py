"""Edição local real: origem, concorrência e publicação após gravação."""
import json
from datetime import date
from http.client import HTTPConnection
from threading import Thread

import pytest

from financas.ingestao import ingerir
from financas.persistencia import Banco
from financas.pluggy import criar_cliente
from financas.servidor import ServicoLocal, criar_servidor


@pytest.fixture
def api(config_offline, tmp_path):
    with Banco.abrir(config_offline.caminho_banco) as banco:
        banco.criar_schema()
        banco.gravar_regras(config_offline.regras)
        ingerir(criar_cliente(config_offline), banco, config_offline.regras, hoje=date(2025, 9, 20))
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html><title>teste</title>", encoding="utf-8")
    servico = ServicoLocal(config_offline, frontend)
    servico.preparar()
    servidor = criar_servidor(servico, 0)
    thread = Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    yield servico, servidor
    servidor.shutdown()
    servidor.server_close()
    thread.join(timeout=2)


def requisitar(api, caminho, metodo="GET", corpo=None, **cabecalhos):
    servico, servidor = api
    porta = servidor.server_port
    headers = {"Origin": f"http://127.0.0.1:{porta}", "Content-Type": "application/json",
               "X-Financas-Token": servico.token, "If-Match": str(servico.revisao)}
    headers.update(cabecalhos)
    conexao = HTTPConnection("127.0.0.1", porta, timeout=15)
    conexao.request(metodo, caminho, body=json.dumps(corpo) if corpo is not None else None, headers=headers)
    resposta = conexao.getresponse()
    dados = resposta.read()
    status = resposta.status
    conexao.close()
    return status, json.loads(dados) if dados else {}


def test_recusa_origem_externa_host_externo_e_token_incorreto(api):
    assert requisitar(api, "/api/estado", Host="ataque.example")[0] == 403
    assert requisitar(api, "/api/estado", Origin="https://ataque.example")[0] == 403
    assert requisitar(api, "/api/ajustes", "PUT", {}, **{"X-Financas-Token": "errado"})[0] == 403
    assert requisitar(api, "/api/ajustes", "PUT", {}, Origin="null")[0] == 403


def test_catalogo_gravacao_e_conflito_entre_abas(api):
    status, catalogo = requisitar(api, "/api/catalogo")
    assert status == 200 and len(catalogo["categorias"]) >= 10
    id_categoria = catalogo["categorias"][0]["id"]
    ajuste = {"tipo": "classificacao", "ids_transacoes": ["tx-nu-c-01"], "id_categoria": id_categoria}
    antiga = str(api[0].revisao)
    status, resultado = requisitar(api, "/api/ajustes", "PUT", ajuste)
    assert status == 200 and resultado["salvo"] and resultado["publicado"]
    assert requisitar(api, "/api/ajustes", "PUT", ajuste, **{"If-Match": antiga})[0] == 409
    assert requisitar(api, "/api/ajustes", "PUT", {"tipo": "desfazer", "ids_transacoes": ["tx-nu-c-01"]})[0] == 200


def test_falha_publicacao_informa_salvo_e_permite_tentar_novamente(api, monkeypatch):
    from financas import servidor as modulo
    from financas.publicacao import ErroDePublicacao
    original = modulo.publicar
    manifesto = api[0].destino / "manifesto.json"
    anterior = manifesto.read_bytes()
    def falhar(*args, **kwargs):
        raise ErroDePublicacao("falha sintética no disco")
    monkeypatch.setattr(modulo, "publicar", falhar)
    status, resultado = requisitar(api, "/api/categorias", "PUT", {"nome": "Minha categoria", "macro_categoria": "Lazer"})
    assert status == 202 and resultado["salvo"] and not resultado["publicado"]
    assert manifesto.read_bytes() == anterior
    assert any(c["nome"] == "Minha categoria" for c in requisitar(api, "/api/catalogo")[1]["categorias"])
    monkeypatch.setattr(modulo, "publicar", original)
    assert requisitar(api, "/api/publicar", "POST", {})[1]["publicado"]
    assert manifesto.read_bytes() != anterior


def test_banco_em_atualizacao_tem_conflito_explicito(api):
    api[0].trava.acquire()
    try:
        assert requisitar(api, "/api/categorias", "PUT", {"nome": "X", "macro_categoria": "Lazer"})[0] == 409
    finally:
        api[0].trava.release()


def test_nao_expoe_arquivos_fora_do_frontend(api):
    assert requisitar(api, "/../.env")[0] == 403
    assert requisitar(api, "/dados/teste.duckdb")[0] == 403
    assert requisitar(api, "/dados/")[0] == 403


def test_duas_instancias_compartilham_revisao_persistente(api):
    from financas.servidor import Conflito
    primeiro = api[0]
    segundo = ServicoLocal(primeiro.config, primeiro.frontend)
    segundo.preparar()
    antiga = segundo.revisao
    primeiro.gravar({"tipo": "categoria", "id": "lazer-geral", "nome": "Primeiro", "macro_categoria": "Lazer"}, primeiro.revisao)
    with pytest.raises(Conflito):
        segundo.gravar({"tipo": "categoria", "id": "lazer-geral", "nome": "Segundo", "macro_categoria": "Lazer"}, antiga)
    reiniciado = ServicoLocal(primeiro.config, primeiro.frontend)
    reiniciado.preparar()
    assert reiniciado.revisao == primeiro.revisao
