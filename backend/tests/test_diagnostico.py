"""
Testes do diagnóstico da conexão.

O comando nasceu de um sintoma real e desconcertante: `POST /auth` responde 200
e a requisição seguinte responde 401. Credencial válida, chave recusada.

Duas coisas precisam ser verdade, e as duas são testáveis sem rede:

1. **Ele distingue as causas.** Um relatório que só diz "deu 401" não vale o
   comando que o gerou. Cada cenário abaixo tem um sintoma diferente no
   relatório.
2. **Ele não vaza segredo.** A saída vai para print de tela e para chat de
   suporte. Nenhum teste aqui usa credencial real, e um deles falha se o valor
   inteiro aparecer na saída.
"""

from __future__ import annotations

import httpx
import pytest

from financas.config import Configuracao
from financas.diagnostico import _mascarar, diagnosticar

SEGREDO = "segredo-falso-que-nao-pode-vazar"


@pytest.fixture
def config(config_online: Configuracao) -> Configuracao:
    return config_online


def rodar(config: Configuracao, atender, monkeypatch):
    """Roda o diagnóstico contra uma API falsa, sem abrir socket."""
    original = httpx.Client

    def cliente_falso(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(atender)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", cliente_falso)
    return diagnosticar(config)


def texto(achados) -> str:
    return "\n".join(str(a) for a in achados)


# ---------------------------------------------------------------------------
# O sintoma que originou o comando
# ---------------------------------------------------------------------------


def test_auth_ok_e_items_401_e_reportado_como_chave_recusada(config, monkeypatch) -> None:
    """Credencial válida, chave recusada — o caso real.

    O relatório precisa deixar claro que o /auth passou, senão a leitura óbvia
    (e errada) é "minhas credenciais estão erradas", e a pessoa vai rotacionar
    credencial que está boa.
    """

    def atender(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.path == "/auth":
            return httpx.Response(200, json={"apiKey": "chave-valida"})
        return httpx.Response(401, json={"message": "Unauthorized", "code": 401})

    saida = texto(rodar(config, atender, monkeypatch))

    assert "POST /auth" in saida and "HTTP 200" in saida
    assert "apiKey recebida" in saida
    assert "recusada por todos os cabeçalhos" in saida


def test_descobre_quando_outro_cabecalho_e_o_aceito(config, monkeypatch) -> None:
    """A hipótese que o comando existe para confirmar ou descartar.

    Se a API passar a querer `Authorization: Bearer`, o cliente precisa mudar —
    e o diagnóstico precisa dizer isso com todas as letras, não deixar a pessoa
    inferir de uma tabela de status.
    """

    def atender(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.path == "/auth":
            return httpx.Response(200, json={"apiKey": "chave"})
        if requisicao.headers.get("Authorization") == "Bearer chave":
            return httpx.Response(200, json={"results": []})
        return httpx.Response(401, json={"message": "Unauthorized"})

    saida = texto(rodar(config, atender, monkeypatch))

    assert "aceitou Authorization, não X-API-KEY" in saida


def test_caminho_feliz_lista_os_itens_e_seus_estados(config, monkeypatch) -> None:
    """Item com status != UPDATED é a causa provável de conta sem transação."""

    def atender(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.path == "/auth":
            return httpx.Response(200, json={"apiKey": "chave"})
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "abcdef12-0000",
                        "connector": {"name": "MeuPluggy"},
                        "status": "UPDATED",
                        "executionStatus": "SUCCESS",
                    },
                    {
                        "id": "99999999-0000",
                        "connector": {"name": "Nubank"},
                        "status": "LOGIN_ERROR",
                        "executionStatus": "ERROR",
                    },
                ]
            },
        )

    achados = rodar(config, atender, monkeypatch)
    saida = texto(achados)

    assert "itens (conexões) encontrados" in saida
    assert "MeuPluggy" in saida and "Nubank" in saida
    assert any(a.ok is False and "LOGIN_ERROR" in a.detalhe for a in achados)


def test_lista_vazia_aponta_o_conector_meupluggy(config, monkeypatch) -> None:
    """Autentica, autoriza, e não há nada: falta a ponte entre os dois portais."""

    def atender(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.path == "/auth":
            return httpx.Response(200, json={"apiKey": "chave"})
        return httpx.Response(200, json={"results": []})

    saida = texto(rodar(config, atender, monkeypatch))

    assert "MeuPluggy" in saida and "dashboard.pluggy.ai" in saida


def test_credencial_recusada_no_proprio_auth(config, monkeypatch) -> None:
    """Caso diferente do anterior: aqui o par realmente está errado."""

    def atender(requisicao: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "client credentials are invalid"})

    saida = texto(rodar(config, atender, monkeypatch))

    assert "POST /auth" in saida and "HTTP 403" in saida
    assert "client credentials are invalid" in saida


def test_campo_apiKey_ausente_e_apontado(config, monkeypatch) -> None:
    """Se a API renomear o campo, o cliente quebra em silêncio; aqui não."""

    def atender(requisicao: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token": "outro-nome"})

    saida = texto(rodar(config, atender, monkeypatch))

    assert "campos devolvidos" in saida and "token" in saida
    assert "ausente ou vazio" in saida


# ---------------------------------------------------------------------------
# Não vazar segredo
# ---------------------------------------------------------------------------


def test_relatorio_nunca_imprime_a_credencial_inteira(config, monkeypatch) -> None:
    """A saída vai para print de tela e para chat de suporte."""

    def atender(requisicao: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"apiKey": SEGREDO})

    saida = texto(rodar(config, atender, monkeypatch))

    assert SEGREDO not in saida
    assert config.client_secret not in saida


@pytest.mark.parametrize(
    "valor, esperado",
    [
        ("abcd1234", "8 caracteres"),
        ("  espaco-no-inicio", "ESPAÇO OU QUEBRA"),
        ('"com-aspas"', "ASPAS SOBRANDO"),
        ("", "VAZIO"),
    ],
)
def test_mascara_flagra_os_erros_de_colar_e_colar(valor, esperado) -> None:
    """Aspas sobrando e espaço no fim são os dois erros mais comuns de .env, e
    os dois produzem falhas que não parecem ter nada a ver com formatação."""
    assert esperado in _mascarar(valor)


# ---------------------------------------------------------------------------
# A apiKey é um JWT, e o payload dela é quem sabe explicar a recusa
# ---------------------------------------------------------------------------


def _jwt(payload: dict) -> str:
    import base64
    import json as _json

    def parte(d):
        bruto = _json.dumps(d).encode()
        return base64.urlsafe_b64encode(bruto).decode().rstrip("=")

    return f"{parte({'alg': 'HS256'})}.{parte(payload)}.assinatura-falsa"


def test_claims_da_apikey_entram_no_relatorio(config, monkeypatch) -> None:
    """Validade, escopo e plano vêm todos no payload do JWT. Sem lê-lo, o
    relatório só consegue dizer 'foi recusada' — que é o que já se sabia."""
    chave = _jwt({"clientId": "abc", "scope": ["ITEMS"], "plan": "TRIAL"})

    def atender(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.path == "/auth":
            return httpx.Response(200, json={"apiKey": chave})
        return httpx.Response(401, json={"message": "Unauthorized"})

    saida = texto(rodar(config, atender, monkeypatch))

    assert "claims da apiKey" in saida
    assert "TRIAL" in saida and "ITEMS" in saida


def test_apikey_vencida_e_apontada(config, monkeypatch) -> None:
    chave = _jwt({"exp": 1000000000})  # 2001

    def atender(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.path == "/auth":
            return httpx.Response(200, json={"apiKey": chave})
        return httpx.Response(401, json={"message": "Unauthorized"})

    saida = texto(rodar(config, atender, monkeypatch))

    assert "JÁ VENCIDA" in saida


def test_claim_de_identidade_aparece_so_como_nome(config, monkeypatch) -> None:
    """O relatório vai para chat de suporte: nome de claim ajuda a diagnosticar,
    valor de claim de identidade é dado pessoal sem utilidade nenhuma ali."""
    chave = _jwt({"email": "matheus@exemplo.com", "cpf": "12345678909"})

    def atender(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.path == "/auth":
            return httpx.Response(200, json={"apiKey": chave})
        return httpx.Response(401, json={"message": "Unauthorized"})

    saida = texto(rodar(config, atender, monkeypatch))

    assert "email" in saida and "cpf" in saida          # os nomes, sim
    assert "matheus@exemplo.com" not in saida           # os valores, não
    assert "12345678909" not in saida


def test_apikey_que_nao_e_jwt_nao_quebra(config, monkeypatch) -> None:
    def atender(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.path == "/auth":
            return httpx.Response(200, json={"apiKey": "chave-simples-nao-jwt"})
        return httpx.Response(200, json={"results": []})

    saida = texto(rodar(config, atender, monkeypatch))

    assert "não é um JWT decodificável" in saida
