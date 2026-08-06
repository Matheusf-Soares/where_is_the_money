"""
Diagnóstico da conexão com a Pluggy.

Existe para um caso específico e desconcertante: `POST /auth` responde 200 e a
requisição seguinte responde 401. Credencial válida, chave recusada. Sem ver a
resposta crua não há como distinguir as causas possíveis, e o cliente normal
esconde tudo isso atrás de exceções — que é o comportamento certo dele, e o
errado para investigar.

Este módulo é deliberadamente burro: faz as requisições na mão, com `httpx`
direto, e mostra o que voltou. Não reaproveita `ClienteHttp` de propósito —
se o problema estiver no cliente, usar o cliente para investigar esconderia
justamente o que se quer ver.

**Nada de segredo é impresso.** Credenciais aparecem como comprimento e
prefixo, o suficiente para flagrar aspas sobrando, espaço no fim ou o campo
trocado, e insuficiente para vazar em print de tela ou em log colado num chat.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from financas.config import Configuracao

# Candidatos a cabeçalho de autenticação. O primeiro é o documentado no
# OpenAPI da Pluggy; os outros existem porque um 401 logo depois de um /auth
# bem-sucedido é exatamente o sintoma de estar mandando a chave no lugar errado,
# e testar é mais barato que discutir.
CABECALHOS_CANDIDATOS = (
    ("X-API-KEY", lambda chave: chave),
    ("Authorization", lambda chave: f"Bearer {chave}"),
    ("authorization", lambda chave: chave),
)


@dataclass
class Achado:
    """Uma linha do relatório."""

    rotulo: str
    detalhe: str
    ok: bool | None = None  # None = informativo, sem juízo

    def __str__(self) -> str:
        marca = {True: "  OK  ", False: "FALHA ", None: "      "}[self.ok]
        return f"{marca} {self.rotulo:<34} {self.detalhe}"


def _mascarar(valor: str) -> str:
    """Mostra o suficiente para diagnosticar, nunca o suficiente para vazar."""
    if not valor:
        return "VAZIO"
    visivel = valor[:4]
    aviso = ""
    if valor != valor.strip():
        aviso = "  <-- TEM ESPAÇO OU QUEBRA DE LINHA NAS PONTAS"
    elif valor[0] in "\"'" or valor[-1] in "\"'":
        aviso = "  <-- TEM ASPAS SOBRANDO"
    return f"{len(valor)} caracteres, começa com {visivel!r}{aviso}"


def _corpo(resposta: httpx.Response, limite: int = 400) -> str:
    try:
        return json.dumps(resposta.json(), ensure_ascii=False)[:limite]
    except ValueError:
        return repr(resposta.text[:limite])


def diagnosticar(config: Configuracao) -> list[Achado]:
    """Roda a bateria e devolve o relatório."""
    achados: list[Achado] = []

    achados.append(Achado("host", config.url_api))
    achados.append(Achado("modo", config.modo))
    achados.append(Achado("PLUGGY_CLIENT_ID", _mascarar(config.client_id or "")))
    achados.append(Achado("PLUGGY_CLIENT_SECRET", _mascarar(config.client_secret or "")))

    if not config.client_id or not config.client_secret:
        achados.append(
            Achado("credenciais", "faltando; preencha o .env", ok=False)
        )
        return achados

    with httpx.Client(base_url=config.url_api, timeout=config.timeout_http) as http:
        # --- 1. autenticação ------------------------------------------------
        try:
            auth = http.post(
                "/auth",
                json={
                    "clientId": config.client_id,
                    "clientSecret": config.client_secret,
                },
            )
        except httpx.TransportError as erro:
            achados.append(Achado("POST /auth", f"não chegou: {erro!r}", ok=False))
            return achados

        achados.append(
            Achado("POST /auth", f"HTTP {auth.status_code}", ok=auth.status_code == 200)
        )
        if auth.status_code != 200:
            achados.append(Achado("resposta", _corpo(auth)))
            return achados

        try:
            corpo: dict[str, Any] = auth.json()
        except ValueError:
            achados.append(Achado("resposta do /auth", "não é JSON", ok=False))
            return achados

        # Os NOMES dos campos, não os valores: se a API passar a devolver
        # `token` em vez de `apiKey`, isto mostra na hora.
        achados.append(Achado("campos devolvidos", ", ".join(sorted(corpo))))

        chave = corpo.get("apiKey")
        if not isinstance(chave, str) or not chave:
            achados.append(
                Achado(
                    "campo apiKey",
                    "ausente ou vazio — é o campo que o cliente lê",
                    ok=False,
                )
            )
            return achados
        achados.append(Achado("apiKey recebida", _mascarar(chave), ok=True))

        # --- 2. qual cabeçalho a API aceita ---------------------------------
        # É a pergunta central quando /auth dá 200 e o resto dá 401.
        aceito = None
        for nome, montar in CABECALHOS_CANDIDATOS:
            try:
                r = http.get("/items", headers={nome: montar(chave)}, params={"page": 1})
            except httpx.TransportError as erro:
                achados.append(Achado(f"GET /items via {nome}", f"{erro!r}", ok=False))
                continue

            achados.append(
                Achado(
                    f"GET /items via {nome}",
                    f"HTTP {r.status_code}"
                    + ("" if r.status_code == 200 else f" — {_corpo(r, 200)}"),
                    ok=r.status_code == 200,
                )
            )
            if r.status_code == 200 and aceito is None:
                aceito = (nome, r)

        if aceito is None:
            achados.append(
                Achado(
                    "conclusão",
                    "a apiKey é recusada por todos os cabeçalhos testados. "
                    "Ver interpretação abaixo.",
                    ok=False,
                )
            )
            return achados

        nome_aceito, resposta = aceito
        if nome_aceito != "X-API-KEY":
            achados.append(
                Achado(
                    "ATENÇÃO",
                    f"a API aceitou {nome_aceito}, não X-API-KEY. "
                    f"O cliente precisa mudar.",
                    ok=False,
                )
            )

        # --- 3. o que existe do outro lado ----------------------------------
        try:
            dados = resposta.json()
        except ValueError:
            dados = {}
        itens = dados.get("results", dados if isinstance(dados, list) else [])
        achados.append(Achado("itens (conexões) encontrados", str(len(itens)), ok=bool(itens)))

        for item in itens[:10]:
            conector = (item.get("connector") or {}).get("name", "?")
            achados.append(
                Achado(
                    f"  item {str(item.get('id'))[:8]}…",
                    f"{conector} · status={item.get('status')} "
                    f"· execução={item.get('executionStatus')}",
                    ok=item.get("status") == "UPDATED",
                )
            )

        if not itens:
            achados.append(
                Achado(
                    "conclusão",
                    "autenticação funciona, mas não há nenhuma conexão nesta "
                    "aplicação. Falta criar o item do conector MeuPluggy (id 200) "
                    "no dashboard.pluggy.ai.",
                    ok=False,
                )
            )

    return achados


INTERPRETACAO_401 = """\
COMO LER UM 401 LOGO DEPOIS DE UM /auth BEM-SUCEDIDO

As credenciais são válidas — o /auth as aceitou. O que foi recusado foi a
apiKey na requisição seguinte. As causas possíveis, da mais comum para a menos:

1. TRIAL EXPIRADO / CONTA SEM ACESSO À API
   A aplicação existe e autentica, mas o acesso aos dados foi cortado quando o
   período de avaliação terminou. É o cenário mais provável em conta gratuita.
   Onde conferir: dashboard.pluggy.ai, na aba de plano ou billing da aplicação.

2. CREDENCIAL DE OUTRO AMBIENTE
   Cada aplicação tem um par por ambiente. Autenticar com o par de um ambiente
   e consultar dados de outro devolve 401.
   Onde conferir: dashboard.pluggy.ai > sua aplicação > credenciais; confirme
   que está copiando as de Desenvolvimento.

3. APLICAÇÃO DESATIVADA OU CREDENCIAL ROTACIONADA PELA METADE
   Se o secret foi rotacionado e só ele foi atualizado no .env, o /auth pode
   passar e a chave sair sem escopo.
   Onde conferir: gere um par novo e substitua os DOIS valores.

O `errorId` que aparece na mensagem de erro é rastreável pelo suporte da
Pluggy. Se nada acima resolver, é o que vale mandar para eles junto do
horário da requisição.\
"""
