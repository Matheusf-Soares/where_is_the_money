"""Sincronização explícita de faturas pela API local, sem efeitos na abertura."""
import json
from pathlib import Path

import pytest

from test_servidor import api, requisitar
from financas.persistencia import Banco
from financas.pluggy.fixtures import ClienteFixtures


@pytest.fixture
def fonte(api, tmp_path, monkeypatch):
    pasta = tmp_path / "fonte-faturas"
    (pasta / "bills").mkdir(parents=True)
    (pasta / "bills" / "conta-nubank-credit.json").write_text(json.dumps([
        {"id": "fatura-sintetica", "dueDate": "2026-09-20T00:00:00Z",
         "totalAmount": 1250, "totalAmountCurrencyCode": "BRL"}
    ]), encoding="utf-8")
    from financas import servidor
    monkeypatch.setattr(servidor, "criar_cliente", lambda config: ClienteFixtures(pasta), raising=False)
    return pasta


def test_sincronizar_faturas_exige_origem_token_e_revisao(api, fonte):
    caminho = "/api/faturas/sincronizar"
    assert requisitar(api, caminho, "POST", {}, Origin="https://fora.example")[0] == 403
    assert requisitar(api, caminho, "POST", {}, **{"X-Financas-Token": "incorreto"})[0] == 403
    assert requisitar(api, caminho, "POST", {}, **{"If-Match": "-1"})[0] == 409


def test_sincronizar_publica_total_oficial_e_muda_revisao(api, fonte):
    antes = api[0].revisao
    status, resultado = requisitar(api, "/api/faturas/sincronizar", "POST", {})
    assert status == 200
    assert resultado["publicado"] and resultado["salvo"]
    assert resultado["faturas"] == 1
    assert resultado["revisao"] == antes + 1
    manifesto = json.loads((api[0].destino / "manifesto.json").read_text(encoding="utf-8"))
    assert manifesto["linhas"]["faturas"] == 1
    with Banco.abrir(api[0].config.caminho_banco) as banco:
        assert banco.conexao.execute("SELECT valor_total FROM faturas").fetchone()[0] == 1250


def test_faturas_salvas_mas_nao_publicadas_podem_ser_republicadas(api, fonte, monkeypatch):
    from financas import servidor
    from financas.publicacao import ErroDePublicacao
    publicar_original = servidor.publicar
    manifesto = api[0].destino / "manifesto.json"
    anterior = manifesto.read_bytes()
    def falhar(*args, **kwargs):
        raise ErroDePublicacao("disco indisponível")
    monkeypatch.setattr(servidor, "publicar", falhar)
    status, resultado = requisitar(api, "/api/faturas/sincronizar", "POST", {})
    assert status == 202 and resultado["salvo"] and not resultado["publicado"]
    assert manifesto.read_bytes() == anterior
    monkeypatch.setattr(servidor, "publicar", publicar_original)
    assert requisitar(api, "/api/publicar", "POST", {})[1]["publicado"]
    assert json.loads(manifesto.read_text(encoding="utf-8"))["linhas"]["faturas"] == 1
